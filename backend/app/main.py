from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.connection import close_pool, run_migrations
from app.routers import formats, generate, health, learn


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle handler."""
    # Startup: initialize DB connection pool and run migrations
    import logging

    logger = logging.getLogger(__name__)
    try:
        await run_migrations()
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Database migration failed: {e}", exc_info=True)
    yield
    # Shutdown: close DB connection pool
    await close_pool()


app = FastAPI(
    title="PDF Forge API",
    lifespan=lifespan,
    debug=settings.DEBUG,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(learn.router, prefix="/api")
app.include_router(formats.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
