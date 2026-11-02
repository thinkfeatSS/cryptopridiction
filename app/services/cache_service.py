import time
import json
import logging
from typing import Any, Optional, Dict
from app.config import settings

logger = logging.getLogger("cache_service")

# Fallback in-memory storage
_LOCAL_MEM_CACHE: Dict[str, Any] = {}
_LOCAL_MEM_EXPIRY: Dict[str, float] = {}

class CacheService:
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        self._redis = None
        self._is_redis_available = False
        self._last_connect_attempt = 0.0
        self._init_client()

    def _init_client(self):
        now = time.time()
        if now - self._last_connect_attempt < 10.0:
            return
        self._last_connect_attempt = now

        try:
            import redis
            client = redis.from_url(
                self.redis_url,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
                max_connections=50
            )
            client.ping()
            self._redis = client
            self._is_redis_available = True
            logger.info(f"[CACHE] Connected to Redis at {self.redis_url}")
        except Exception as e:
            self._redis = None
            self._is_redis_available = False

    @property
    def is_available(self) -> bool:
        if not self._is_redis_available:
            self._init_client()
        return self._is_redis_available

    def get_raw(self, key: str) -> Optional[str]:
        """Gets raw string value from Redis or local in-memory fallback without json deserialization."""
        if self.is_available and self._redis:
            try:
                val = self._redis.get(key)
                return val
            except Exception:
                self._is_redis_available = False

        # Memory Fallback
        now = time.time()
        if key in _LOCAL_MEM_CACHE:
            if now < _LOCAL_MEM_EXPIRY.get(key, 0.0):
                return _LOCAL_MEM_CACHE[key]
            else:
                _LOCAL_MEM_CACHE.pop(key, None)
                _LOCAL_MEM_EXPIRY.pop(key, None)
        return None

    def set_raw(self, key: str, value: str, ttl_seconds: int = 10) -> bool:
        """Saves raw string value to Redis with TTL without extra json serialization."""
        if self.is_available and self._redis:
            try:
                self._redis.setex(key, ttl_seconds, str(value))
                return True
            except Exception:
                self._is_redis_available = False

        # Memory Fallback
        _LOCAL_MEM_CACHE[key] = str(value)
        _LOCAL_MEM_EXPIRY[key] = time.time() + ttl_seconds
        return True

    def get_json(self, key: str) -> Optional[Any]:
        """Gets and parses JSON value from Redis or local in-memory fallback."""
        if self.is_available and self._redis:
            try:
                val = self._redis.get(key)
                if val is not None:
                    return json.loads(val)
                return None
            except Exception:
                self._is_redis_available = False

        # Memory Fallback
        now = time.time()
        if key in _LOCAL_MEM_CACHE:
            if now < _LOCAL_MEM_EXPIRY.get(key, 0.0):
                return _LOCAL_MEM_CACHE[key]
            else:
                _LOCAL_MEM_CACHE.pop(key, None)
                _LOCAL_MEM_EXPIRY.pop(key, None)
        return None

    def set_json(self, key: str, value: Any, ttl_seconds: int = 10) -> bool:
        """Serializes and saves value to Redis with TTL."""
        serialized = json.dumps(value, default=str)
        if self.is_available and self._redis:
            try:
                self._redis.setex(key, ttl_seconds, serialized)
                return True
            except Exception:
                self._is_redis_available = False

        # Memory Fallback
        _LOCAL_MEM_CACHE[key] = value
        _LOCAL_MEM_EXPIRY[key] = time.time() + ttl_seconds
        return True

    def delete(self, key: str):
        """Deletes a key from Redis and memory."""
        if self.is_available and self._redis:
            try:
                self._redis.delete(key)
            except Exception:
                pass
        _LOCAL_MEM_CACHE.pop(key, None)
        _LOCAL_MEM_EXPIRY.pop(key, None)

    def publish_event(self, channel: str, message: dict) -> bool:
        """Publishes a real-time event to a Redis Pub/Sub channel."""
        if self.is_available and self._redis:
            try:
                self._redis.publish(channel, json.dumps(message, default=str))
                return True
            except Exception:
                self._is_redis_available = False
        return False

cache_service = CacheService()
