import json
from app.utils.logger import logger

CHANNEL = "wealtheasy:dashboard"

async def publish(event: dict):
    """Publish event to Redis channel — works across processes."""
    from app.cache import get_redis_client
    client = get_redis_client()
    await client.publish(CHANNEL, json.dumps(event))
    logger.info(f"Published '{event.get('event')}' to Redis channel")