from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.core.config import Settings
from app.db.repository import ArticleRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = ArticleRepository(config.database_path)
        repository.initialize()
        app.state.repository = repository
        yield

    application = FastAPI(title="Axiom", version="0.1.0",
                          description="Market intelligence and paper-trading research foundation",
                          lifespan=lifespan)

    @application.get("/health")
    def health_check():
        return {"status": "ok", "service": "axiom", "trading_mode": config.trading_mode}

    application.include_router(router)
    return application


app = create_app()
