"""FastAPI 应用入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth_routes import audit_router, auth_router, users_router
from app.api.batch_routes import batch_router
from app.api.collab_routes import collab_router
from app.api.routes import router
from app.core.config import settings
from app.models import init_db

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(collab_router)
app.include_router(batch_router)
app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# 静态前端（Phase 4：单页 HTML + Vanilla JS + Tailwind CDN）
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        index_html = _FRONTEND_DIR / "index.html"
        if index_html.exists():
            return FileResponse(index_html)
        return {"name": settings.app_name, "docs": "/docs"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        """老式浏览器仍然会自动请求 /favicon.ico，回 SVG 以消除 404。"""
        svg = _FRONTEND_DIR / "favicon.svg"
        if svg.exists():
            return FileResponse(svg, media_type="image/svg+xml")
        return FileResponse(svg, status_code=404)
else:
    @app.get("/")
    def root() -> dict:
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}
