import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
import sys
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            mode.value &= ~0x0040  # Disable ENABLE_QUICK_EDIT_MODE
            mode.value |= 0x0080   # Enable ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(handle, mode)
    except Exception:
        pass
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
from src.database import engine, Base, async_session_maker
from src.common.exceptions import DomainException
from src.common.envelope import error_response
from src.domains.auth.service import AuthService
from src.domains.translation import models as translation_models  # noqa: F401
from src.domains.auth.router import router as auth_router
from src.domains.manga.router import router as manga_router
from src.domains.jobs.router import router as jobs_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables for local MVP if not exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
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
