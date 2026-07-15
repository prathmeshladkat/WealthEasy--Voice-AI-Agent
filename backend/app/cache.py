import json 
from typing import Optional
from unittest import result
from unittest import result

import redis.asyncio as redis

from app.config import settings

CACHE_TTL_SECONDS = 24 * 60 * 60 

_redis_client: Optional[redis.Redis] = None

def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_client

def _build_key(user_id: int, tool_name: str, args_signature: str) -> str:
    """
    Builds the redis key string.
    Kept as a separate function to allow for future changes in key structure.
    """
    return f"tool:{user_id}:{tool_name}:{args_signature}"

async def get_cached(
        user_id: int,
        tool_name: str,
        args_signature: str = "_",

) -> Optional[dict]:
    """
    Returns the cached result dict, or None if not in cache.
    json.loads() converts json string back to a Python dict.
    """

    redis_client = get_redis_client()
    key = _build_key(user_id, tool_name, args_signature)
    raw = await redis_client.get(key)

    if raw is None:
        return None
    
    return json.loads(raw)

async def set_cached(
    user_id: int,
    tool_name: str,
    result: dict,
    args_signature: str = "_",
) -> None:
    """
    json.dumps() converts the dict to a json string because Redis
    stores strings, not Python objects.
    ex=CACHE_TTL_SECONDS tells Redis to auto-delete this key
    after 24 hours — we never need to clean up manually.
    """
    client = get_redis_client()
    key = _build_key(user_id, tool_name, args_signature)
    await client.set(key, json.dumps(result), ex=CACHE_TTL_SECONDS)

    
async def invalidate_cached(
    user_id: int,
    tool_name: str,
    args_signature: str = "_",
) -> None:
    """
    Deletes a specific cache entry.
    Not used in the main flow right now — but useful if we ever
    want to force a fresh DB fetch for a specific user/tool combo
    (e.g. after a SIP payment is processed).
    """
    client = get_redis_client()
    key = _build_key(user_id, tool_name, args_signature)
    await client.delete(key)
 
 
async def check_redis_connection() -> bool:
    """Startup health check — same pattern as check_db_connection()."""
    client = get_redis_client()
    response = await client.ping()
    return response is True
    