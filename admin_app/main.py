"""Home Fileshare Admin - desktop control panel.

A CustomTkinter app to edit config.yaml, manage users and per-folder
read/write grants (directly in SQLite), control the uvicorn server, and
display the LAN URL.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from admin_app import config_io, elevation, network
from admin_app.db_admin import AdminDb
from admin_app.paths import install_root
from admin_app.server_control import ServerProcess
from server.config import Settings

REPO_ROOT = install_root()

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class AdminApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Home Fileshare Admin")
        self.geometry("980x680")
        self.minsize(900, 600)

        config_io.ensure_config_exists()
        self.settings: Settings = config_io.load_settings()
        self.db = AdminDb(self.settings)
        self.server = ServerProcess()
        self.server.set_callbacks(on_log=self._on_server_log)

        self._build_layout()
        self._show_tab("connection")
        self._poll_status()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=190, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Home\nFileshare",
            font=ctk.CTkFont(size=22, weight="bold"),
            justify="left",
        ).grid(row=0, column=0, padx=20, pady=(22, 18), sticky="w")

        self._nav_buttons: dict = {}
        tabs = [
            ("connection", "Connection"),
            ("settings", "Settings"),
            ("users", "Users"),
            ("grants", "Grants"),
            ("server", "Server Control"),
        ]
        for i, (key, label) in enumerate(tabs, start=1):
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                height=40,
                corner_radius=8,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray25"),
                command=lambda k=key: self._show_tab(k),
            )
            btn.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            self._nav_buttons[key] = btn

        self.status_label = ctk.CTkLabel(
            sidebar, text="\u25cf Stopped", text_color="#d9534f"
        )
        self.status_label.grid(row=8, column=0, padx=20, pady=(0, 8), sticky="w")

        appearance = ctk.CTkOptionMenu(
            sidebar,
            values=["System", "Light", "Dark"],
            command=lambda m: ctk.set_appearance_mode(m),
            width=150,
        )
        appearance.grid(row=9, column=0, padx=20, pady=(0, 18))

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._frames: dict = {}
        self._frames["connection"] = self._build_connection_tab()
        self._frames["settings"] = self._build_settings_tab()
        self._frames["users"] = self._build_users_tab()
        self._frames["grants"] = self._build_grants_tab()
        self._frames["server"] = self._build_server_tab()

    def _show_tab(self, key: str) -> None:
        for frame in self._frames.values():
            frame.grid_forget()
        self._frames[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=("gray75", "gray25"))
            else:
                btn.configure(fg_color="transparent")

        if key == "connection":
            self._refresh_connection()
        elif key == "users":
            self._refresh_users()
        elif key == "grants":
            self._refresh_grants()
        elif key == "settings":
            self._load_settings_into_form()

    # ------------------------------------------------------------------
    # Connection tab
    # ------------------------------------------------------------------
    def _build_connection_tab(self) -> ctk.CTkFrame:
        f = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            f, text="Connection", font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(
            f,
            text="Open this address on your phone (same Wi-Fi) to use the server.",
            text_color=("gray40", "gray60"),
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        card = ctk.CTkFrame(f)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(
            card,
            text="http://...",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=("#1f6aa5", "#5aa9e6"),
        )
        self.url_label.grid(row=0, column=0, padx=20, pady=(20, 6), sticky="w")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="w")
        ctk.CTkButton(
            btn_row, text="Copy URL", width=110, command=self._copy_url
        ).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkButton(
            btn_row,
            text="Open in browser",
            width=140,
            fg_color="transparent",
            border_width=1,
            command=self._open_url_browser,
        ).grid(row=0, column=1)

        ctk.CTkLabel(
            f, text="All network addresses", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=3, column=0, sticky="w", pady=(6, 6))
        self.ip_list_frame = ctk.CTkFrame(f)
        self.ip_list_frame.grid(row=4, column=0, sticky="ew")
        self.ip_list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            f, text="Refresh", width=110, command=self._refresh_connection
        ).grid(row=5, column=0, sticky="w", pady=16)

        return f

    def _refresh_connection(self) -> None:
        port = self.settings.port
        primary = network.primary_lan_ip() or "127.0.0.1"
        self.url_label.configure(text=f"http://{primary}:{port}")
        self._current_url = f"http://{primary}:{port}"

        for child in self.ip_list_frame.winfo_children():
            child.destroy()

        ips = network.all_ipv4_addresses() or ["127.0.0.1"]
        for i, ip in enumerate(ips):
            url = f"http://{ip}:{port}"
            row = ctk.CTkFrame(self.ip_list_frame, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=10, pady=4)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=url, anchor="w").grid(
                row=0, column=0, sticky="w"
            )
            ctk.CTkButton(
                row,
                text="Copy",
                width=70,
                command=lambda u=url: self._copy_text(u),
            ).grid(row=0, column=1, padx=6)

    def _copy_url(self) -> None:
        self._copy_text(getattr(self, "_current_url", ""))

    def _copy_text(self, text: str) -> None:
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    def _open_url_browser(self) -> None:
        import webbrowser

        url = getattr(self, "_current_url", None)
        if url:
            webbrowser.open(url)

    # ------------------------------------------------------------------
    # Settings tab
    # ------------------------------------------------------------------
    def _build_settings_tab(self) -> ctk.CTkFrame:
        f = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            f, text="Settings", font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        self._setting_vars: dict = {}
        r = 1

        def add_label(text: str, row: int) -> None:
            ctk.CTkLabel(f, text=text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=8
            )

        # data_root with folder picker
        add_label("Data folder (data_root)", r)
        self._setting_vars["data_root"] = tk.StringVar()
        ctk.CTkEntry(f, textvariable=self._setting_vars["data_root"]).grid(
            row=r, column=1, sticky="ew", pady=8
        )
        ctk.CTkButton(
            f, text="Browse", width=90, command=self._pick_data_root
        ).grid(row=r, column=2, padx=(8, 0))
        r += 1

        # host
        add_label("Host", r)
        self._setting_vars["host"] = tk.StringVar()
        ctk.CTkEntry(f, textvariable=self._setting_vars["host"]).grid(
            row=r, column=1, columnspan=2, sticky="ew", pady=8
        )
        r += 1

        # port
        add_label("Port", r)
        self._setting_vars["port"] = tk.StringVar()
        ctk.CTkEntry(f, textvariable=self._setting_vars["port"], width=140).grid(
            row=r, column=1, sticky="w", pady=8
        )
        r += 1

        # jwt secret with show/hide
        add_label("JWT secret", r)
        self._setting_vars["jwt_secret"] = tk.StringVar()
        self._jwt_entry = ctk.CTkEntry(
            f, textvariable=self._setting_vars["jwt_secret"], show="*"
        )
        self._jwt_entry.grid(row=r, column=1, sticky="ew", pady=8)
        self._jwt_show = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            f,
            text="Show",
            variable=self._jwt_show,
            command=self._toggle_jwt,
            width=60,
        ).grid(row=r, column=2, padx=(8, 0))
        r += 1

        # jwt expire minutes
        add_label("Session length (minutes)", r)
        self._setting_vars["jwt_expire_minutes"] = tk.StringVar()
        ctk.CTkEntry(
            f, textvariable=self._setting_vars["jwt_expire_minutes"], width=140
        ).grid(row=r, column=1, sticky="w", pady=8)
        r += 1

        # allow_public_registration
        add_label("Allow public registration", r)
        self._setting_vars["allow_public_registration"] = tk.BooleanVar()
        ctk.CTkSwitch(
            f,
            text="",
            variable=self._setting_vars["allow_public_registration"],
        ).grid(row=r, column=1, sticky="w", pady=8)
        r += 1

        # chunk_size_mb
        add_label("Chunk size (MB)", r)
        self._setting_vars["chunk_size_mb"] = tk.StringVar()
        ctk.CTkEntry(
            f, textvariable=self._setting_vars["chunk_size_mb"], width=140
        ).grid(row=r, column=1, sticky="w", pady=8)
        r += 1

        # mobile_chunk_size_mb
        add_label("Mobile chunk size (MB)", r)
        self._setting_vars["mobile_chunk_size_mb"] = tk.StringVar()
        ctk.CTkEntry(
            f, textvariable=self._setting_vars["mobile_chunk_size_mb"], width=140
        ).grid(row=r, column=1, sticky="w", pady=8)
        r += 1

        # max_parallel_parts
        add_label("Max parallel parts", r)
        self._setting_vars["max_parallel_parts"] = tk.StringVar()
        ctk.CTkEntry(
            f, textvariable=self._setting_vars["max_parallel_parts"], width=140
        ).grid(row=r, column=1, sticky="w", pady=8)
        r += 1

        # ip_allowlist (multiline)
        add_label("IP allowlist (one per line)", r)
        self._ip_allowlist_box = ctk.CTkTextbox(f, height=70)
        self._ip_allowlist_box.grid(
            row=r, column=1, columnspan=2, sticky="ew", pady=8
        )
        r += 1

        # cors_origins (multiline)
        add_label("CORS origins (one per line)", r)
        self._cors_box = ctk.CTkTextbox(f, height=70)
        self._cors_box.grid(row=r, column=1, columnspan=2, sticky="ew", pady=8)
        r += 1

        note = ctk.CTkLabel(
            f,
            text=(
                "Note: bootstrap admin password only applies on first run. "
                "To change a live password, use the Users tab.\n"
                "Changing the JWT secret will log out all users."
            ),
            text_color=("gray40", "gray60"),
            justify="left",
            anchor="w",
        )
        note.grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 6))
        r += 1

        btns = ctk.CTkFrame(f, fg_color="transparent")
        btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=10)
        ctk.CTkButton(btns, text="Save", width=120, command=self._save_settings).grid(
            row=0, column=0, padx=(0, 10)
        )
        ctk.CTkButton(
            btns,
            text="Reload",
            width=120,
            fg_color="transparent",
            border_width=1,
            command=self._load_settings_into_form,
        ).grid(row=0, column=1)

        return f

    def _toggle_jwt(self) -> None:
        self._jwt_entry.configure(show="" if self._jwt_show.get() else "*")

    def _pick_data_root(self) -> None:
        initial = self._setting_vars["data_root"].get() or str(REPO_ROOT)
        chosen = filedialog.askdirectory(initialdir=initial, title="Select data folder")
        if chosen:
            self._setting_vars["data_root"].set(chosen)

    def _load_settings_into_form(self) -> None:
        self.settings = config_io.load_settings()
        s = self.settings
        self._setting_vars["data_root"].set(s.data_root)
        self._setting_vars["host"].set(s.host)
        self._setting_vars["port"].set(str(s.port))
        self._setting_vars["jwt_secret"].set(s.jwt_secret)
        self._setting_vars["jwt_expire_minutes"].set(str(s.jwt_expire_minutes))
        self._setting_vars["allow_public_registration"].set(
            s.allow_public_registration
        )
        self._setting_vars["chunk_size_mb"].set(str(s.chunk_size_mb))
        self._setting_vars["mobile_chunk_size_mb"].set(str(s.mobile_chunk_size_mb))
        self._setting_vars["max_parallel_parts"].set(str(s.max_parallel_parts))

        self._ip_allowlist_box.delete("1.0", "end")
        self._ip_allowlist_box.insert("1.0", "\n".join(s.ip_allowlist))
        self._cors_box.delete("1.0", "end")
        self._cors_box.insert("1.0", "\n".join(s.cors_origins))

    def _collect_settings(self) -> dict:
        def lines(box: ctk.CTkTextbox) -> list:
            raw = box.get("1.0", "end").strip()
            return [ln.strip() for ln in raw.splitlines() if ln.strip()]

        return {
            "data_root": self._setting_vars["data_root"].get().strip(),
            "host": self._setting_vars["host"].get().strip() or "0.0.0.0",
            "port": int(self._setting_vars["port"].get()),
            "jwt_secret": self._setting_vars["jwt_secret"].get(),
            "jwt_expire_minutes": int(
                self._setting_vars["jwt_expire_minutes"].get()
            ),
            "allow_public_registration": bool(
                self._setting_vars["allow_public_registration"].get()
            ),
            "chunk_size_mb": int(self._setting_vars["chunk_size_mb"].get()),
            "mobile_chunk_size_mb": int(
                self._setting_vars["mobile_chunk_size_mb"].get()
            ),
            "max_parallel_parts": int(
                self._setting_vars["max_parallel_parts"].get()
            ),
            "ip_allowlist": lines(self._ip_allowlist_box),
            "cors_origins": lines(self._cors_box) or ["*"],
        }

    def _save_settings(self) -> None:
        old_port = self.settings.port
        old_secret = self.settings.jwt_secret
        try:
            values = self._collect_settings()
        except ValueError:
            messagebox.showerror(
                "Invalid input", "Port, session length, and sizes must be numbers."
            )
            return

        if values["jwt_secret"] != old_secret:
            if not messagebox.askyesno(
                "Change JWT secret?",
                "Changing the JWT secret will log out all current users. Continue?",
            ):
                return

        try:
            self.settings = config_io.save_settings(values)
        except Exception as e:
            messagebox.showerror("Could not save", str(e))
            return

        self.db = AdminDb(self.settings)
        messagebox.showinfo("Saved", "Settings saved to config.yaml.")

        if values["port"] != old_port:
            if messagebox.askyesno(
                "Update firewall?",
                f"Port changed to {values['port']}. Open the Windows firewall "
                "for the new port now? (requires admin)",
            ):
                self._open_firewall()

        if self.server.is_running():
            if messagebox.askyesno(
                "Restart server?",
                "The server is running. Restart it to apply the new settings?",
            ):
                self.server.restart(self.settings.host, self.settings.port)

        self._refresh_connection()

    # ------------------------------------------------------------------
    # Users tab
    # ------------------------------------------------------------------
    def _build_users_tab(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(f, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Users", font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header, text="+ Add user", width=120, command=self._add_user_dialog
        ).grid(row=0, column=1, sticky="e")

        cols = ctk.CTkFrame(f)
        cols.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for i, (txt, w) in enumerate(
            [("ID", 60), ("Username", 240), ("Admin", 80), ("Actions", 320)]
        ):
            cols.grid_columnconfigure(i, weight=1 if i == 1 else 0)
            ctk.CTkLabel(
                cols, text=txt, font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=i, sticky="w", padx=10, pady=6)

        self.users_scroll = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.users_scroll.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self.users_scroll.grid_columnconfigure(1, weight=1)

        return f

    def _refresh_users(self) -> None:
        for child in self.users_scroll.winfo_children():
            child.destroy()
        try:
            users = self.db.list_users()
        except Exception as e:
            messagebox.showerror("Database error", str(e))
            return

        for i, u in enumerate(users):
            ctk.CTkLabel(self.users_scroll, text=str(u.id), width=60).grid(
                row=i, column=0, sticky="w", padx=10, pady=6
            )
            ctk.CTkLabel(self.users_scroll, text=u.username, anchor="w").grid(
                row=i, column=1, sticky="w", padx=10, pady=6
            )
            ctk.CTkLabel(
                self.users_scroll,
                text="Yes" if u.is_admin else "No",
                width=80,
            ).grid(row=i, column=2, sticky="w", padx=10, pady=6)

            actions = ctk.CTkFrame(self.users_scroll, fg_color="transparent")
            actions.grid(row=i, column=3, sticky="e", padx=6)
            ctk.CTkButton(
                actions,
                text="Password",
                width=90,
                command=lambda uu=u: self._change_password_dialog(uu),
            ).grid(row=0, column=0, padx=3)
            ctk.CTkButton(
                actions,
                text="Demote" if u.is_admin else "Promote",
                width=90,
                fg_color="transparent",
                border_width=1,
                command=lambda uu=u: self._toggle_admin(uu),
            ).grid(row=0, column=1, padx=3)
            ctk.CTkButton(
                actions,
                text="Delete",
                width=80,
                fg_color="#d9534f",
                hover_color="#c9302c",
                command=lambda uu=u: self._delete_user(uu),
            ).grid(row=0, column=2, padx=3)

    def _add_user_dialog(self) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title("Add user")
        dlg.geometry("360x300")
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Username").pack(anchor="w", padx=20, pady=(20, 2))
        username = ctk.CTkEntry(dlg)
        username.pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text="Password").pack(anchor="w", padx=20, pady=(12, 2))
        password = ctk.CTkEntry(dlg, show="*")
        password.pack(fill="x", padx=20)

        is_admin = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(dlg, text="Administrator", variable=is_admin).pack(
            anchor="w", padx=20, pady=14
        )

        def submit() -> None:
            try:
                self.db.create_user(
                    username.get(), password.get(), is_admin.get()
                )
            except Exception as e:
                messagebox.showerror("Could not add user", str(e), parent=dlg)
                return
            dlg.destroy()
            self._refresh_users()

        ctk.CTkButton(dlg, text="Create", command=submit).pack(
            padx=20, pady=10, fill="x"
        )

    def _change_password_dialog(self, user) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Password: {user.username}")
        dlg.geometry("360x200")
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text=f"New password for {user.username}").pack(
            anchor="w", padx=20, pady=(20, 2)
        )
        password = ctk.CTkEntry(dlg, show="*")
        password.pack(fill="x", padx=20)

        def submit() -> None:
            try:
                self.db.set_password(user.id, password.get())
            except Exception as e:
                messagebox.showerror("Could not update", str(e), parent=dlg)
                return
            dlg.destroy()
            messagebox.showinfo("Updated", f"Password changed for {user.username}.")

        ctk.CTkButton(dlg, text="Update", command=submit).pack(
            padx=20, pady=20, fill="x"
        )

    def _toggle_admin(self, user) -> None:
        try:
            self.db.set_admin(user.id, not user.is_admin)
        except Exception as e:
            messagebox.showerror("Could not update", str(e))
            return
        self._refresh_users()

    def _delete_user(self, user) -> None:
        if not messagebox.askyesno(
            "Delete user",
            f"Delete user '{user.username}' and all their folder grants?",
        ):
            return
        try:
            self.db.delete_user(user.id)
        except Exception as e:
            messagebox.showerror("Could not delete", str(e))
            return
        self._refresh_users()

    # ------------------------------------------------------------------
    # Grants tab
    # ------------------------------------------------------------------
    def _build_grants_tab(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(f, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Folder permissions", font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header,
            text="+ Add / edit grant",
            width=160,
            command=lambda: self._grant_dialog(),
        ).grid(row=0, column=1, sticky="e")

        cols = ctk.CTkFrame(f)
        cols.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        headers = [
            ("User", 150),
            ("Logical path", 150),
            ("Physical path", 280),
            ("Read", 60),
            ("Write", 60),
            ("Actions", 150),
        ]
        for i, (txt, _w) in enumerate(headers):
            cols.grid_columnconfigure(i, weight=1 if i in (1, 2) else 0)
            ctk.CTkLabel(
                cols, text=txt, font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=i, sticky="w", padx=10, pady=6)

        self.grants_scroll = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.grants_scroll.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        for i in (1, 2):
            self.grants_scroll.grid_columnconfigure(i, weight=1)

        return f

    def _refresh_grants(self) -> None:
        for child in self.grants_scroll.winfo_children():
            child.destroy()
        try:
            grants = self.db.list_grants()
        except Exception as e:
            messagebox.showerror("Database error", str(e))
            return

        for i, g in enumerate(grants):
            ctk.CTkLabel(self.grants_scroll, text=g.username).grid(
                row=i, column=0, sticky="w", padx=10, pady=6
            )
            ctk.CTkLabel(self.grants_scroll, text=g.logical_path, anchor="w").grid(
                row=i, column=1, sticky="w", padx=10, pady=6
            )
            ctk.CTkLabel(
                self.grants_scroll, text=g.physical_path, anchor="w"
            ).grid(row=i, column=2, sticky="w", padx=10, pady=6)
            ctk.CTkLabel(
                self.grants_scroll, text="\u2713" if g.can_read else "\u2014", width=60
            ).grid(row=i, column=3, padx=10, pady=6)
            ctk.CTkLabel(
                self.grants_scroll, text="\u2713" if g.can_write else "\u2014", width=60
            ).grid(row=i, column=4, padx=10, pady=6)

            actions = ctk.CTkFrame(self.grants_scroll, fg_color="transparent")
            actions.grid(row=i, column=5, sticky="e", padx=6)
            ctk.CTkButton(
                actions,
                text="Edit",
                width=60,
                command=lambda gg=g: self._grant_dialog(gg),
            ).grid(row=0, column=0, padx=3)
            ctk.CTkButton(
                actions,
                text="Delete",
                width=70,
                fg_color="#d9534f",
                hover_color="#c9302c",
                command=lambda gg=g: self._delete_grant(gg),
            ).grid(row=0, column=1, padx=3)

    def _grant_dialog(self, grant=None) -> None:
        try:
            users = self.db.list_users()
        except Exception as e:
            messagebox.showerror("Database error", str(e))
            return
        if not users:
            messagebox.showwarning(
                "No users", "Create a user first in the Users tab."
            )
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title("Grant" if grant is None else "Edit grant")
        dlg.geometry("520x360")
        dlg.transient(self)
        dlg.grab_set()

        usernames = [u.username for u in users]
        ctk.CTkLabel(dlg, text="User").pack(anchor="w", padx=20, pady=(20, 2))
        user_var = tk.StringVar(
            value=grant.username if grant else usernames[0]
        )
        ctk.CTkOptionMenu(dlg, values=usernames, variable=user_var).pack(
            fill="x", padx=20
        )

        ctk.CTkLabel(dlg, text="Logical path (what users see)").pack(
            anchor="w", padx=20, pady=(12, 2)
        )
        logical = ctk.CTkEntry(dlg)
        logical.pack(fill="x", padx=20)
        logical.insert(0, grant.logical_path if grant else "/")

        ctk.CTkLabel(
            dlg, text=f"Physical folder (must be under {self.settings.data_root})"
        ).pack(anchor="w", padx=20, pady=(12, 2))
        phys_row = ctk.CTkFrame(dlg, fg_color="transparent")
        phys_row.pack(fill="x", padx=20)
        phys_row.grid_columnconfigure(0, weight=1)
        physical = ctk.CTkEntry(phys_row)
        physical.grid(row=0, column=0, sticky="ew")
        physical.insert(
            0, grant.physical_path if grant else self.settings.data_root
        )

        def pick() -> None:
            initial = physical.get() or self.settings.data_root
            chosen = filedialog.askdirectory(initialdir=initial, parent=dlg)
            if chosen:
                physical.delete(0, "end")
                physical.insert(0, chosen)

        ctk.CTkButton(phys_row, text="Browse", width=90, command=pick).grid(
            row=0, column=1, padx=(8, 0)
        )

        perms = ctk.CTkFrame(dlg, fg_color="transparent")
        perms.pack(anchor="w", padx=20, pady=14)
        can_read = tk.BooleanVar(value=grant.can_read if grant else True)
        can_write = tk.BooleanVar(value=grant.can_write if grant else False)
        ctk.CTkCheckBox(perms, text="Read", variable=can_read).grid(
            row=0, column=0, padx=(0, 20)
        )
        ctk.CTkCheckBox(perms, text="Write", variable=can_write).grid(
            row=0, column=1
        )

        def submit() -> None:
            try:
                self.db.upsert_grant(
                    user_var.get(),
                    logical.get(),
                    physical.get(),
                    can_read.get(),
                    can_write.get(),
                )
            except Exception as e:
                messagebox.showerror("Could not save grant", str(e), parent=dlg)
                return
            dlg.destroy()
            self._refresh_grants()

        ctk.CTkButton(dlg, text="Save", command=submit).pack(
            fill="x", padx=20, pady=10
        )

    def _delete_grant(self, grant) -> None:
        if not messagebox.askyesno(
            "Delete grant",
            f"Remove access of '{grant.username}' to {grant.logical_path}?",
        ):
            return
        try:
            self.db.delete_grant(grant.id)
        except Exception as e:
            messagebox.showerror("Could not delete", str(e))
            return
        self._refresh_grants()

    # ------------------------------------------------------------------
    # Server control tab
    # ------------------------------------------------------------------
    def _build_server_tab(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            f, text="Server control", font=ctk.CTkFont(size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        controls = ctk.CTkFrame(f)
        controls.grid(row=1, column=0, sticky="ew")
        self.start_btn = ctk.CTkButton(
            controls, text="Start", width=100, command=self._start_server
        )
        self.start_btn.grid(row=0, column=0, padx=10, pady=10)
        self.stop_btn = ctk.CTkButton(
            controls,
            text="Stop",
            width=100,
            fg_color="#d9534f",
            hover_color="#c9302c",
            command=self._stop_server,
        )
        self.stop_btn.grid(row=0, column=1, padx=10, pady=10)
        ctk.CTkButton(
            controls, text="Restart", width=100, command=self._restart_server
        ).grid(row=0, column=2, padx=10, pady=10)
        self.server_status = ctk.CTkLabel(
            controls, text="\u25cf Stopped", text_color="#d9534f"
        )
        self.server_status.grid(row=0, column=3, padx=20)

        tools = ctk.CTkFrame(f)
        tools.grid(row=2, column=0, sticky="ew", pady=12)
        tool_buttons = [
            ("Open firewall", self._open_firewall),
            ("Install service", self._install_service),
            ("Uninstall service", self._uninstall_service),
            ("Open data folder", self._open_data_folder),
            ("Edit config.yaml", self._open_config),
        ]
        for i, (label, cmd) in enumerate(tool_buttons):
            ctk.CTkButton(
                tools,
                text=label,
                width=150,
                fg_color="transparent",
                border_width=1,
                command=cmd,
            ).grid(row=0, column=i, padx=6, pady=10)

        log_frame = ctk.CTkFrame(f)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(log_frame, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head, text="Server log", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=6)
        ctk.CTkButton(
            head, text="Clear", width=80, command=self._clear_log
        ).grid(row=0, column=1, padx=10)

        self.log_box = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Consolas"))
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_box.configure(state="disabled")

        return f

    def _start_server(self) -> None:
        self.settings = config_io.load_settings()
        try:
            self.server.start(self.settings.host, self.settings.port)
        except Exception as e:
            messagebox.showerror("Could not start server", str(e))

    def _stop_server(self) -> None:
        self.server.stop()

    def _restart_server(self) -> None:
        self.settings = config_io.load_settings()
        try:
            self.server.restart(self.settings.host, self.settings.port)
        except Exception as e:
            messagebox.showerror("Could not start server", str(e))

    def _clear_log(self) -> None:
        self.server.clear_logs()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_server_log(self, line: str) -> None:
        # Called from the reader thread; marshal to UI thread.
        self.after(0, lambda: self._append_log_line(line))

    def _append_log_line(self, line: str) -> None:
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except tk.TclError:
            pass

    def _open_firewall(self) -> None:
        try:
            elevation.open_firewall(self.settings.port)
        except Exception as e:
            messagebox.showerror("Firewall", str(e))

    def _install_service(self) -> None:
        if not messagebox.askyesno(
            "Install service",
            "Install Home Fileshare as a Windows service?\n"
            "This requires NSSM (nssm.exe) in PATH and admin rights.",
        ):
            return
        try:
            elevation.install_service()
        except Exception as e:
            messagebox.showerror("Service", str(e))

    def _uninstall_service(self) -> None:
        if not messagebox.askyesno(
            "Uninstall service", "Remove the Home Fileshare Windows service?"
        ):
            return
        try:
            elevation.uninstall_service()
        except Exception as e:
            messagebox.showerror("Service", str(e))

    def _open_data_folder(self) -> None:
        from admin_app.paths import resolved_data_root

        path = resolved_data_root(self.settings)
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.run(["xdg-open", str(path)])

    def _open_config(self) -> None:
        path = config_io.CONFIG_PATH
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.run(["xdg-open", str(path)])

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------
    def _poll_status(self) -> None:
        running = self.server.is_running()
        if running:
            text, color = "\u25cf Running", "#5cb85c"
        else:
            text, color = "\u25cf Stopped", "#d9534f"
        self.status_label.configure(text=text, text_color=color)
        if hasattr(self, "server_status"):
            self.server_status.configure(text=text, text_color=color)
        self.after(1000, self._poll_status)

    def _on_close(self) -> None:
        if self.server.is_running():
            if messagebox.askyesno(
                "Quit",
                "The server is still running. Stop it and quit?",
            ):
                self.server.stop()
            else:
                return
        self.destroy()


def main() -> None:
    app = AdminApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
