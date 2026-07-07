from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy models."""
    pass

async def get_db_session() -> AsyncSession:
    """Dependency for injecting database sessions into FastAPI routes."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
