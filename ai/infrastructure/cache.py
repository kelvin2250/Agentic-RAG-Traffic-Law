import redis.asyncio as aioredis
from typing import Optional, Any
import json
from .config import settings

class RedisCache:
    """Async Redis Client Wrapper phục vụ việc lưu trữ cache hội thoại hoặc context"""
    def __init__(self):
        self.redis_url = settings.redis_url
        self._client: Optional[aioredis.Redis] = None

    def get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        """Lấy dữ liệu từ cache và tự động decode JSON"""
        client = self.get_client()
        data = await client.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = 3600) -> bool:
        """Lưu dữ liệu vào cache, tự động hóa chuỗi JSON và cài đặt TTL (giây)"""
        client = self.get_client()
        string_value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return await client.set(key, string_value, ex=ttl)

    async def delete(self, key: str) -> bool:
        """Xóa một key khỏi cache"""
        client = self.get_client()
        return await client.delete(key) > 0

# Khởi tạo đối tượng toàn cục để sử dụng async
cache = RedisCache()