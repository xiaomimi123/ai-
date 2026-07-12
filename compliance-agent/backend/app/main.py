"""FastAPI 应用入口（v3 内控评价智能审核系统）。

清理过程中：仅暴露 auth/users/audit-logs；v3 新路由将在 commit 2/3 引入。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.audit_routes import findings_router, materials_router, tasks_router, units_router
from app.api.auth_routes import audit_router, auth_router, users_router
from app.api.export_routes import exports_router
from app.api.knowledge_routes import checkitems_router, indicators_router
from app.api.regulation_routes import regulations_router
from app.api.settings_routes import settings_router
from app.core.config import settings
from app.models import init_db

app = FastAPI(title=settings.app_name, version="3.0.0")

# gzip 压缩：app.js 130KB → ~25KB，HTML/JSON 也压。
# minimum_size 阈值用默认 500 字节，避免小响应反而变慢。
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(settings_router)
app.include_router(indicators_router)
app.include_router(checkitems_router)
app.include_router(regulations_router)
app.include_router(units_router)
app.include_router(tasks_router)
app.include_router(findings_router)
app.include_router(materials_router)
app.include_router(exports_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# 静态前端
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if not _FRONTEND_DIR.exists():
    _FRONTEND_DIR = Path("/frontend")

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
        svg = _FRONTEND_DIR / "favicon.svg"
        if svg.exists():
            return FileResponse(svg, media_type="image/svg+xml")
        return FileResponse(svg, status_code=404)
else:
    @app.get("/")
    def root() -> dict:
        return {"name": settings.app_name, "docs": "/docs"}


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_default_provider": settings.llm_provider,
        "embedder": settings.embedder,
        "vector_store": settings.vector_store,
    }
