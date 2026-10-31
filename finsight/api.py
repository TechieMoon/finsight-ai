import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from finsight.config import Settings, settings
from finsight.dart import Limiter, RateLimit
from finsight.models import Answer, Question
from finsight.workflow import Agent


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings()
    lock = threading.Lock()
    limiter = Limiter(config.api_calls_per_minute)

    @asynccontextmanager
    async def lifespan(app):
        app.state.agent = Agent(config)
        yield
        client = getattr(app.state.agent.financial_client, "client", None)
        if client:
            client.close()

    app = FastAPI(title="FinSight AI", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": config.finsight_mode,
            "live_providers_verified": False,
            "scope": "annual CFS/OFS, KRW",
        }

    @app.post("/analyze", response_model=Answer)
    def analyze(request: Question):
        try:
            limiter.acquire()
        except RateLimit as exc:
            raise HTTPException(429, str(exc)) from None
        if not lock.acquire(blocking=False):
            raise HTTPException(503, "다른 분석이 진행 중입니다. 잠시 후 다시 시도하세요.")
        try:
            return app.state.agent.run(request)
        except Exception:  # noqa: BLE001 -- redact SDK exceptions at the HTTP boundary
            # Intentionally no exception interpolation: SDK exceptions can contain API-key query strings.
            raise HTTPException(
                503, "분석을 완료하지 못했습니다. 설정과 데이터 저장소 상태를 확인하세요."
            ) from None
        finally:
            lock.release()

    return app


app = create_app()
