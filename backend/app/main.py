from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
# from fastapi_limiter.FastAPILimiter import FastAPILimiter

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tạo bảng database nếu chưa tồn tại (Auto-creation)
    from app.core.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Startup: Kết nối Redis phục vụ Rate Limiter
    # redis = aioredis.from_url(
    #     settings.redis_url,
    #     encoding="utf-8",
    #     decode_responses=True
    # )
    # await FastAPILimiter.init(redis)
    yield
    # Shutdown: Đóng kết nối Redis
    # await redis.close()


app = FastAPI(
    title="Traffic Law Web Backend",
    description="Web server backend quản lý Auth, Session và trung chuyển kết nối AI Service",
    version="1.0.0",
    lifespan=lifespan
)

# Cấu hình CORS cho phép Frontend truy cập
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Đăng ký các API router
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat_router, prefix="/api/v1/chat", tags=["Chat"])


@app.get("/")
async def root():
    return {
        "service": "Vietnam Traffic Law Web Backend Gateway",
        "status": "online",
        "documentation": "/docs"
    }
