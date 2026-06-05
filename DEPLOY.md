# Deploy Home Fileshare on another Windows PC

Use this guide to run the server on a **second PC** (with admin if possible) so your iPhone can reach it on the LAN.

## What you need

| Item | Notes |
|------|--------|
| Windows 10/11 PC | Always-on or on when you transfer files |
| Python 3.11+ | [python.org](https://www.python.org/downloads/) — check **“Add python.exe to PATH”** during install |
| Same Wi‑Fi as iPhone | PC and phone on the same home network |
| Admin (recommended) | Only for opening firewall port 8443; app itself does not require admin |

## 1. Copy the project to the new PC

Copy the whole `fileshare` folder (USB, git clone, zip, etc.) to e.g.:

```
C:\Apps\fileshare\
```

Required contents:

```
fileshare/
  server/
  web/
  scripts/
  requirements.txt
  config.example.yaml
  run_server.bat
```

You do **not** need to copy `venv/` or `data/` from the old machine (recreate them on the new PC).

## 2. Configure

In PowerShell or Command Prompt:

```bat
cd C:\Apps\fileshare
copy config.example.yaml config.yaml
notepad config.yaml
```

Edit at minimum:

```yaml
host: "0.0.0.0"          # must be 0.0.0.0 for iPhone/LAN access (not 127.0.0.1)
port: 8443
data_root: "D:/FileShareData"   # where photos/videos are stored
bootstrap_admin_password: "your-strong-password"
jwt_secret: "long-random-string-at-least-32-chars"
```

Create the data folder if needed:

```bat
mkdir D:\FileShareData
```

## 3. Install and start (no admin)

```bat
cd C:\Apps\fileshare
run_server.bat
```

First run creates `venv`, installs packages, and starts the server on **all interfaces** (`0.0.0.0:8443`).

Leave this window open while testing. You should see:

```
INFO:     Uvicorn running on http://0.0.0.0:8443
```

**On the server PC:** open `http://127.0.0.1:8443` → login `admin` / your password.

## 4. Find the LAN IP (for iPhone)

On the server PC:

```bat
ipconfig
```

Use the **IPv4 Address** on **Wi-Fi** or **Ethernet** — usually `192.168.x.x` or `10.x.x.x`.

Avoid addresses on virtual adapters (WSL, VMware, Hyper-V) such as `172.31.x.x` unless that is your real LAN NIC.

**On iPhone (Safari):**

```
http://<IPv4-from-ipconfig>:8443
```

Example: `http://192.168.1.50:8443`

Optional: **Add to Home Screen** for a quick app icon.

## 5. Firewall (admin required on that PC)

If iPhone shows **connection refused** but `127.0.0.1` works on the PC, the server is fine — Windows is blocking inbound port 8443.

**PowerShell as Administrator:**

```powershell
cd C:\Apps\fileshare
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\open_firewall.ps1 -Port 8443
```

Or one line:

```powershell
New-NetFirewallRule -DisplayName "Home Fileshare" -Direction Inbound -Protocol TCP -LocalPort 8443 -Action Allow -Profile Private,Domain
```

Ensure the network is set to **Private** (Settings → Network → Wi‑Fi/Ethernet → Private network).

### No admin on that PC either?

- Ask IT to allow inbound **TCP 8443** on Private profile, or
- Temporarily test with Windows Firewall off (only on a trusted home LAN, not recommended long-term), or
- Use another PC/user account that can add the rule once.

## 6. Add users and folders (admin account)

After login as `admin`, from **another machine on the LAN** or on the server PC (PowerShell):

```powershell
$base = "http://192.168.1.50:8443"   # server PC IP
$login = Invoke-RestMethod -Uri "$base/api/v1/auth/login" -Method Post `
  -ContentType "application/json" `
  -Body '{"username":"admin","password":"YOUR_ADMIN_PASSWORD"}'
$h = @{ Authorization = "Bearer $($login.access_token)" }

# New user
Invoke-RestMethod -Uri "$base/api/v1/admin/users" -Method Post -Headers $h `
  -ContentType "application/json" `
  -Body '{"username":"alice","password":"alice-secret","is_admin":false}'

# Folder on disk + grant
New-Item -ItemType Directory -Force -Path "D:\FileShareData\alice"
Invoke-RestMethod -Uri "$base/api/v1/admin/grants" -Method Put -Headers $h `
  -ContentType "application/json" `
  -Body (@{
    username = "alice"
    logical_path = "/alice"
    physical_path = "D:\FileShareData\alice"
    can_read = $true
    can_write = $true
  } | ConvertTo-Json)
```

Alice opens the same URL, logs in, and sees `/alice` for upload/download.

## 7. Run at login (optional, no NSSM)

Without admin you cannot install a Windows service easily. Options:

**A. Shortcut in Startup folder**

1. Create shortcut to `C:\Apps\fileshare\run_server.bat`
2. Win+R → `shell:startup` → paste shortcut

**B. Task Scheduler (current user, no admin)**

1. Task Scheduler → Create Task
2. Trigger: At log on
3. Action: Start program → `C:\Apps\fileshare\run_server.bat`
4. Start in: `C:\Apps\fileshare`

## 8. Run as Windows service (admin, scheduled task)

If the new PC has admin (starts at boot, no logged-in user required, no
extra downloads):

1. Run once: `run_server.bat` (creates `venv`)
2. Administrator PowerShell:

```powershell
cd C:\Apps\fileshare
.\scripts\install_service.ps1 -Port 8443
```

Remove it later with:

```powershell
.\scripts\uninstall_service.ps1
```

## 9. Verify checklist

| Step | OK? |
|------|-----|
| `run_server.bat` running, no errors | |
| PC browser: `http://127.0.0.1:8443` login works | |
| `netstat -ano \| findstr 8443` shows `0.0.0.0:8443` | |
| iPhone: `http://<LAN-IP>:8443` loads login page | |
| Upload a photo from iPhone | |
| Download it back | |

## 10. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `127.0.0.1` works, iPhone refused | Firewall rule (section 5) or wrong IP (section 4) |
| `172.31.x.x` does not work | That is often not your Wi‑Fi IP — use `ipconfig` Wi‑Fi IPv4 |
| `ModuleNotFoundError: server` | Run from `fileshare` folder; use `run_server.bat` |
| Port in use | `netstat -ano \| findstr 8443` then `taskkill /PID <pid> /F` |
| Slow uploads | PC on Ethernet, iPhone on 5 GHz; exclude `data_root` from antivirus scan |

## 11. Files to back up

- `config.yaml` (secrets)
- `data/fileshare.db` (users & grants)
- `D:\FileShareData\` (or your `data_root`) — actual photos/videos

## Quick reference

```bat
cd C:\Apps\fileshare
copy config.example.yaml config.yaml
:: edit config.yaml
run_server.bat
```

iPhone URL: `http://<server-LAN-IPv4>:8443`

More detail: [README.md](README.md) · Native iOS later: [docs/IOS_CLIENT.md](docs/IOS_CLIENT.md)
