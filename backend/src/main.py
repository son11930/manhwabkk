import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import sys
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for std_id in (-10, -11, -12):
            handle = kernel32.GetStdHandle(std_id)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                mode.value &= ~0x0040  # Disable ENABLE_QUICK_EDIT_MODE
                mode.value |= 0x0080   # Enable ENABLE_EXTENDED_FLAGS
                kernel32.SetConsoleMode(handle, mode)
        # Prevent Windows 11 Efficiency Mode / background throttling when minimized or unfocused
        NORMAL_PRIORITY_CLASS = 0x00000020
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), NORMAL_PRIORITY_CLASS)
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
from src.logging_config import configure_logging
from src.database import engine, Base, async_session_maker
from src.common.exceptions import DomainException
from src.common.envelope import error_response
from src.domains.auth.service import AuthService
from src.domains.translation import models as translation_models  # noqa: F401
from src.domains.auth.router import router as auth_router
from src.domains.manga.router import router as manga_router
from src.domains.jobs.router import router as jobs_router

configure_logging(settings)

def _sync_migrate(connection):
    from sqlalchemy import inspect, text
    inspector = inspect(connection)
    if "translation_jobs" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("translation_jobs")}
        new_cols = [
            ("translation_provider", "VARCHAR(50) DEFAULT 'groq'"),
            ("requested_model", "VARCHAR(100)"),
            ("actual_model", "VARCHAR(100)"),
            ("input_tokens", "INTEGER DEFAULT 0"),
            ("output_tokens", "INTEGER DEFAULT 0"),
            ("cost_estimate_usd", "FLOAT DEFAULT 0.0"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in columns:
                connection.execute(text(f"ALTER TABLE translation_jobs ADD COLUMN {col_name} {col_type}"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables for local MVP if not exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_migrate)
    
    # Initialize default Super Admin
    async with async_session_maker() as session:
        auth_service = AuthService(session)
        await auth_service.initialize_super_admin()
        
    yield
    # Shutdown: dispose engine
    await engine.dispose()

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(DomainException)
async def domain_exception_handler(request: Request, exc: DomainException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.message).model_dump()
    )

# Include Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(manga_router, prefix=settings.API_V1_STR)
app.include_router(jobs_router, prefix=settings.API_V1_STR)

import os
from fastapi.staticfiles import StaticFiles
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}
