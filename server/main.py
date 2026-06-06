from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server.acl import PathAccessError
from server.admin_routes import router as admin_router
from server.bootstrap import bootstrap_admin, ensure_data_root
from server.config import get_settings, load_settings
from server.database import init_db
from server.routes import router as api_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _client_allowed(client_ip: str, allowlist: list) -> bool:
    if not allowlist:
        return True
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def create_app() -> FastAPI:
    load_settings()
    settings = get_settings()

    app = FastAPI(
        title="Home Fileshare",
        description="LAN photo/video file server with per-user folder ACLs",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def ip_allowlist_middleware(request: Request, call_next):
        if settings.ip_allowlist and request.url.path.startswith("/api/"):
            client = request.client.host if request.client else ""
            if not _client_allowed(client, settings.ip_allowlist):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "IP not allowed"},
                )
        return await call_next(request)

    # iOS Safari aggressively caches HTML/JS/CSS for PWAs. Force revalidation so
    # users always get the latest UI without needing a private tab.
    _NO_CACHE_PATHS = {"/", "/index.html", "/app.js", "/styles.css", "/manifest.json"}

    @app.middleware("http")
    async def no_cache_static_middleware(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in _NO_CACHE_PATHS or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.on_event("startup")
    async def startup():
        init_db()
        ensure_data_root()
        bootstrap_admin()

    app.include_router(api_router)
    app.include_router(admin_router, prefix="/api/v1")

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()


def main():
    import uvicorn

    from server.tls import ensure_server_cert

    load_settings()
    s = get_settings()

    kwargs = dict(
        host=s.host,
        port=s.port,
        reload=False,
        timeout_keep_alive=600,
    )

    ssl_files = ensure_server_cert(s)
    if ssl_files:
        cert_file, key_file = ssl_files
        kwargs["ssl_certfile"] = cert_file
        kwargs["ssl_keyfile"] = key_file
        print(f"HTTPS enabled on https://{s.host}:{s.port} (cert: {cert_file})")
    else:
        print(f"HTTP on http://{s.host}:{s.port} (use_https is off)")

    uvicorn.run("server.main:app", **kwargs)


if __name__ == "__main__":
    main()
