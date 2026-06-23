"""FastAPI 앱 팩토리·기동 — 지도·검색 API + SPA 정적 서빙 (ADR-0008·ADR-0009)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from eddr.server.deps import AppState, ServerConfig, build_state
from eddr.server.routes import geocode, map, photos, search, status

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(state: AppState) -> FastAPI:
    """라우터를 조립한 FastAPI 앱을 만든다 — 상태는 인자 주입(테스트와 동형 경로)."""
    app = FastAPI(title="EDDR API")
    app.state.eddr = state
    # GeoJSON 일괄(raw ~1MB)을 gzip해 첫 페이로드를 ~200KB로 — prd §6-b·§8 목표.
    # 이미 압축된 썸네일/원본 바이너리는 압축 이득이 없지만 minimum_size로 작은
    # 응답은 건너뛰고, JSON 응답에만 실효적으로 적용된다.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.include_router(geocode.router)
    app.include_router(map.router)
    app.include_router(photos.router)
    app.include_router(search.router)
    app.include_router(status.router)
    dist = state.config.root / "web" / "dist"
    if dist.is_dir():
        # SPA 정적 서빙(prod, M2) — /api 라우터 뒤에 마운트해 우선순위 유지.
        # dev는 Vite 프록시(web/vite.config.ts)라 이 마운트를 타지 않는다.
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="spa")
    return app


def serve_api(config: ServerConfig, host: str = "127.0.0.1", port: int = 8000) -> None:
    """실데이터로 AppState를 조립하고 uvicorn을 기동한다 (blocking).

    LAN 바인딩은 명시 선택 + 기동 경고가 계약 — 공개 인터넷 직노출 금지
    (ADR-0008 무인증 가드).
    """
    import uvicorn

    if host not in _LOOPBACK_HOSTS:
        print(
            f"⚠️  {host} 바인딩 — 무인증 API가 네트워크에 노출됩니다. 신뢰 LAN에서만 쓰고, "
            "원격 접근은 Tailscale을 권장합니다 (ADR-0008)."
        )
    state = build_state(config)
    uvicorn.run(create_app(state), host=host, port=port)
