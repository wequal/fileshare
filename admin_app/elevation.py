"""Helpers to run PowerShell scripts elevated via UAC.

The admin app stays unprivileged; only firewall and service-install
operations need elevation, which we obtain by launching a single
``powershell.exe`` invocation with ``-Verb RunAs``.
"""

from __future__ import annotations

import subprocess

from admin_app.paths import install_root

REPO_ROOT = install_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _run_elevated(ps_command: str) -> None:
    """Invoke the given PowerShell command line elevated via Start-Process."""
    # Outer powershell calls inner one with RunAs to trigger UAC prompt.
    # The command is embedded inside a double-quoted string below, so escape
    # the characters that are special there (backtick, $, ") -- NOT single
    # quotes, which are literal inside double quotes.
    quoted = (
        ps_command.replace("`", "``").replace("$", "`$").replace('"', '`"')
    )
    outer = (
        "Start-Process powershell -Verb RunAs "
        "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',"
        f"'-Command',\"{quoted}\""
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", outer],
        check=True,
    )


def open_firewall(port: int, rule_name: str = "Home Fileshare") -> None:
    script = SCRIPTS_DIR / "open_firewall.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Missing {script}")
    cmd = (
        f"& '{script}' -Port {int(port)} -RuleName '{rule_name}'; "
        "Read-Host 'Done. Press Enter to close'"
    )
    _run_elevated(cmd)


def install_service(port: int = 8443) -> None:
    script = SCRIPTS_DIR / "install_service.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Missing {script}")
    cmd = (
        f"& '{script}' -Port {int(port)}; "
        "Read-Host 'Done. Press Enter to close'"
    )
    _run_elevated(cmd)


def uninstall_service() -> None:
    script = SCRIPTS_DIR / "uninstall_service.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Missing {script}")
    cmd = (
        f"& '{script}'; "
        "Read-Host 'Done. Press Enter to close'"
    )
    _run_elevated(cmd)
