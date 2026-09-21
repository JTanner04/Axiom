import asyncio
import hmac
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.api.workbench import router as workbench
from app.core.config import Settings
from app.db.repository import ArticleRepository
from app.trading.engine import Engine

logger = logging.getLogger('axiom')
STATIC = Path(__file__).parent / 'static'


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = ArticleRepository(config.database_path)
        repository.initialize()
        service = Engine(config)
        service.initialize()
        app.state.repository = repository
        app.state.engine = service

        async def worker():
            while True:
                await asyncio.sleep(config.poll_seconds)
                with service.store.connection() as db:
                    prefs = service.store.preferences(db, service.scope)
                if prefs['polling']:
                    try:
                        await asyncio.to_thread(service.run_cycle)
                    except Exception:
                        logger.exception('Scheduled ingestion failed')
        task = asyncio.create_task(worker())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    application = FastAPI(title='Axiom',version='0.2.0',description='Market intelligence and paper-trading workbench',lifespan=lifespan)

    @application.middleware('http')
    async def security(request: Request, call_next):
        if request.url.path.startswith('/api/'):
            token = config.api_token.get_secret_value()
            if token and not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+token):
                return JSONResponse({'detail':'API token required'},status_code=401)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                origin = request.headers.get('origin')
                if origin and origin != str(request.base_url).rstrip('/'):
                    return JSONResponse({'detail':'Cross-origin writes are disabled'},status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.path=='/' or request.url.path.startswith('/static/'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @application.get('/health')
    def health_check():
        return {'status':'ok','service':'axiom','trading_mode':config.trading_mode}

    @application.get('/',include_in_schema=False)
    def index():
        return FileResponse(STATIC/'index.html')

    application.mount('/static',StaticFiles(directory=STATIC),name='static')
    application.include_router(router)
    application.include_router(workbench)
    return application


app = create_app()
