"""Run the file share server (uvicorn) as a managed subprocess.

The admin app spawns ``python -m uvicorn server.main:app`` and pipes
combined stdout/stderr into an in-memory ring buffer that the UI tails.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Deque, List, Optional

from admin_app.paths import install_root, is_frozen, venv_python

REPO_ROOT = install_root()

LogCallback = Callable[[str], None]


def _python_exe() -> str:
    """Resolve the python interpreter used to run the server.

    Prefers the local ``venv`` so it matches ``run_server.bat``. When running
    as a frozen ``.exe`` we must NOT fall back to ``sys.executable`` (that is
    the admin app itself, which would just open another admin window instead
    of starting the server).
    """
    venv_py = venv_python()
    if venv_py.is_file():
        return str(venv_py)

    if is_frozen():
        raise FileNotFoundError(
            "Could not find the Python virtual environment at:\n"
            f"  {venv_py}\n\n"
            "Place HomeFileshareAdmin.exe inside the project folder (next to "
            "the 'server' folder) and run run_server.bat once to create the "
            "venv and install dependencies."
        )
    return sys.executable


class ServerProcess:
    """Manages the lifecycle of a uvicorn subprocess."""

    LOG_LIMIT = 1000

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._buf: Deque[str] = deque(maxlen=self.LOG_LIMIT)
        self._lock = threading.Lock()
        self._on_log: Optional[LogCallback] = None
        self._on_exit: Optional[LogCallback] = None

    # ---- public API ----------------------------------------------------

    def is_running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    def set_callbacks(
        self,
        on_log: Optional[LogCallback] = None,
        on_exit: Optional[LogCallback] = None,
    ) -> None:
        self._on_log = on_log
        self._on_exit = on_exit

    def get_logs(self) -> List[str]:
        with self._lock:
            return list(self._buf)

    def clear_logs(self) -> None:
        with self._lock:
            self._buf.clear()

    def start(self, host: str, port: int, settings=None) -> None:
        if self.is_running():
            return

        cmd = [
            _python_exe(),
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--timeout-keep-alive",
            "600",
        ]

        if settings is not None and getattr(settings, "use_https", False):
            from server.tls import ensure_server_cert

            ssl_files = ensure_server_cert(settings)
            if ssl_files:
                cert_file, key_file = ssl_files
                cmd += [
                    "--ssl-certfile",
                    cert_file,
                    "--ssl-keyfile",
                    key_file,
                ]

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        creationflags = 0
        if sys.platform == "win32":
            # Hide the spawned console window and make it killable as a group.
            creationflags = (
                subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )

        self._buf.clear()
        self._append_log(f"$ {' '.join(cmd)}")

        self._proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self._reader = threading.Thread(
            target=self._pump, name="uvicorn-log-reader", daemon=True
        )
        self._reader.start()

    def stop(self, timeout: float = 8.0) -> None:
        p = self._proc
        if p is None or p.poll() is not None:
            return

        try:
            if sys.platform == "win32":
                # Try graceful shutdown first via CTRL_BREAK to the group.
                try:
                    p.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
                except Exception:
                    p.terminate()
            else:
                p.terminate()
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def restart(self, host: str, port: int, settings=None) -> None:
        self.stop()
        self.start(host, port, settings)

    # ---- internal ------------------------------------------------------

    def _append_log(self, line: str) -> None:
        with self._lock:
            self._buf.append(line)
        if self._on_log:
            try:
                self._on_log(line)
            except Exception:
                pass

    def _pump(self) -> None:
        p = self._proc
        if p is None or p.stdout is None:
            return
        try:
            for raw in p.stdout:
                self._append_log(raw.rstrip("\r\n"))
        except Exception as e:
            self._append_log(f"[log reader error] {e}")
        finally:
            code = p.wait()
            self._append_log(f"[server exited with code {code}]")
            if self._on_exit:
                try:
                    self._on_exit(f"exit {code}")
                except Exception:
                    pass
