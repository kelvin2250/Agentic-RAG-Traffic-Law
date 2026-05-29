# ai/api/middleware.py
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("ai.api.middleware")

def setup_middleware(app: FastAPI) -> None:
    """
    Cấu hình CORS và các middleware giám sát cho FastAPI.
    """
    # 1. CORS Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Timing and Logging Middleware
    @app.middleware("http")
    async def log_requests_and_timing(request: Request, call_next):
        start_time = time.time()
        method = request.method
        path = request.url.path
        
        logger.info(f"Received request: {method} {path}")
        
        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
            
            logger.info(
                f"📤 Response sent: {method} {path} - "
                f"Status: {response.status_code} - "
                f"Time: {process_time:.2f}ms"
            )
            return response
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.error(
                f"💥 Request failed: {method} {path} - "
                f"Error: {str(e)} - "
                f"Time: {process_time:.2f}ms"
            )
            raise e
