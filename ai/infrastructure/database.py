from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings
import logging

logger = logging.getLogger(__name__)

_async_engine = None
_async_session_factory = None

def get_engine():
    global _async_engine
    if _async_engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL chưa được cấu hình. Không thể khởi tạo database engine.")
        _async_engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20
        )
    return _async_engine

def get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        _async_session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    return _async_session_factory

async def get_db_session():
    """Dependency Provider sinh session (sử dụng với 'async with')"""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise