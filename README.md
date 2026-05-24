# Home Fileshare

LAN photo and video server for iPhone (Safari / PWA) and future native iOS apps. Per-user folders with read/write ACLs, fast parallel uploads, and streaming downloads.

## Features

- Web UI for iPhone Safari (Add to Home Screen supported)
- JWT login; admin-managed users and folder grants
- TFTP-like semantics: authenticated upload (PUT) and download (GET) per assigned folder
- Simple upload for small files; **parallel chunked upload** for large videos (8 MiB chunks, up to 6 parallel connections)
- Windows-friendly: firewall script, optional NSSM service

## Deploy on another PC

Full step-by-step (copy folder, config, firewall, iPhone URL, users): **[DEPLOY.md](DEPLOY.md)**

## Quick start (Windows)

1. Copy config and edit passwords:

   ```bat
   copy config.example.yaml config.yaml
   ```

   Set `data_root` (e.g. `D:/FileShareData`), change `jwt_secret` and `bootstrap_admin_password`.

2. Run:

   ```bat
   run_server.bat
   ```

3. On the same PC, open `http://127.0.0.1:8443` — sign in as `admin` / password from config.

4. On iPhone (same Wi‑Fi), open `http://<PC-LAN-IP>:8443`.

5. Open firewall (PowerShell **as Administrator**):

   ```powershell
   .\scripts\open_firewall.ps1 -Port 8443
   ```

## Admin: second user and folder

After login as admin, use API or curl from a PC:

```powershell
$token = (Invoke-RestMethod -Uri http://127.0.0.1:8443/api/v1/auth/login -Method Post -ContentType "application/json" -Body '{"username":"admin","password":"changeme"}').access_token
$h = @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Uri http://127.0.0.1:8443/api/v1/admin/users -Method Post -Headers $h -ContentType "application/json" -Body '{"username":"alice","password":"secret123","is_admin":false}'

# Create folder on disk, then grant
New-Item -ItemType Directory -Force -Path D:\FileShareData\alice
Invoke-RestMethod -Uri http://127.0.0.1:8443/api/v1/admin/grants -Method Put -Headers $h -ContentType "application/json" -Body (@{
  username = "alice"
  logical_path = "/alice"
  physical_path = "D:\FileShareData\alice"
  can_read = $true
  can_write = $true
} | ConvertTo-Json)
```

`logical_path` is what users see in the app; `physical_path` must live under `data_root`.

## API overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/register` | Register (if enabled) |
| GET | `/api/v1/auth/me` | Current user + roots |
| GET | `/api/v1/files?path=` | List directory |
| GET | `/api/v1/files/download?path=` | Download file |
| POST | `/api/v1/files/upload?path=` | Simple upload |
| POST | `/api/v1/files/uploads` | Start parallel upload |
| PUT | `/api/v1/files/uploads/{id}/parts/{n}` | Upload part |
| POST | `/api/v1/files/uploads/{id}/complete` | Finish upload |
| DELETE | `/api/v1/files?path=` | Delete file/folder |
| POST | `/api/v1/files/mkdir?path=` | Create folder |

Admin: `/api/v1/admin/users`, `/api/v1/admin/grants`.

Full spec: run `venv\Scripts\python scripts\export_openapi.py` → `docs/openapi.yaml`.

Native iOS notes: [docs/IOS_CLIENT.md](docs/IOS_CLIENT.md).

## Maximum transfer speed

- Connect the Windows PC to the router with **Ethernet (Gigabit+)**.
- Use iPhone **5 GHz Wi‑Fi** close to the AP.
- Exclude `data_root` from real-time antivirus scanning.
- Do not enable NTFS compression on the share folder.
- Tune in `config.yaml`: `chunk_size_mb` (8–16), `max_parallel_parts` (4–6).
- Large videos use parallel upload automatically in the web UI.

## Run as Windows service

1. Install [NSSM](https://nssm.cc/).
2. Create venv via `run_server.bat` once.
3. As Administrator:

   ```powershell
   .\scripts\install_service.ps1
   nssm start HomeFileshare
   ```

## Security

- Change default admin password and `jwt_secret` before use.
- Use `ip_allowlist` in config to limit to LAN subnets.
- Do not port-forward to the internet without VPN (e.g. Tailscale).
- HTTP is acceptable on a trusted LAN; use HTTPS for stricter setups.

## Project layout

```
fileshare/
  server/          # FastAPI backend
  web/             # Safari PWA client
  scripts/         # Firewall, service, OpenAPI export
  docs/            # OpenAPI + iOS guide
  config.yaml      # Local config (gitignored)
```

## License

Private / home use.
