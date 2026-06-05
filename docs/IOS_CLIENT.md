# Native iOS client (phase 2)

The server exposes a REST API identical to the Safari web client. Use the OpenAPI spec in [openapi.yaml](openapi.yaml) to generate Swift models or hand-wire `URLSession`.

## Base URL

```
http://<windows-pc-lan-ip>:8443/api/v1
```

Store the LAN hostname in UserDefaults; discover via Bonjour later if needed.

## Authentication

1. `POST /auth/login` with JSON `{"username","password"}`.
2. Response: `access_token`, `token_type` (`bearer`), `username`, `is_admin`.
3. Send `Authorization: Bearer <token>` on every file request.
4. Persist token in **Keychain** (not UserDefaults).

`GET /auth/me` returns `roots[]` with `logical_path`, `can_read`, `can_write` for UI roots.

## TFTP-like file operations

| Intent | HTTP | Notes |
|--------|------|-------|
| List directory | `GET /files?path=/photos` | JSON `entries[]` |
| Download (GET) | `GET /files/download?path=/photos/img.heic` | Stream to disk; use `URLSessionDownloadTask` |
| Upload (PUT, simple) | `POST /files/upload?path=/photos` | `multipart/form-data` field `file` |
| Upload (PUT, fast) | See multipart flow below | Required for large `.mov` |
| Delete | `DELETE /files?path=...` | Requires write grant |
| New folder | `POST /files/mkdir?path=/photos/2024` | Requires write grant |

Paths are **logical** paths from grants (e.g. `/alice`, `/shared`), not Windows paths.

## Parallel multipart upload (recommended for video)

1. `POST /files/uploads`  
   Body: `{"path":"/photos","filename":"clip.mov","total_size":123456789}`  
   Response: `upload_id`, `chunk_size`, `total_parts`, `expires_at`.

2. For each missing part `n` in `1..total_parts`:  
   `PUT /files/uploads/{upload_id}/parts/{n}`  
   Body: raw bytes (`application/octet-stream`), length = `chunk_size` except last part.

3. `GET /files/uploads/{upload_id}` — resume: upload only parts not in `parts_received`.

4. `POST /files/uploads/{upload_id}/complete` — merges parts; returns final `path`, `size`.

Use **4–6 parallel** `URLSessionUploadTask` or `dataTask` workers. Match server `chunk_size` from step 1.

## Admin (optional in app)

If `is_admin`, call `/api/v1/admin/users` and `/api/v1/admin/grants` — same as web admin tools or a separate macOS/PC script.

## Suggested Swift structure

- `AuthService` — login, token refresh (re-login on 401)
- `FileAPIClient` — list, download, delete
- `MultipartUploader` — initiate / parts / complete with progress `Progress` per file
- `PhotoPickerCoordinator` — `PHPickerViewController` for camera roll selection
- Background transfers: `URLSessionConfiguration.background(withIdentifier:)`

## Security

- Prefer HTTPS with a self-signed cert pinned in the app when moving beyond pure LAN.
- Do not embed admin credentials in the app.

## OpenAPI

Run from project root:

```bat
venv\Scripts\python scripts\export_openapi.py
```

Generated files: `docs/openapi.json`, `docs/openapi.yaml`.
