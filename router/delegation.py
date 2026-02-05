import re
import json
import redis.asyncio as redis

DELEGATE_PATTERN = re.compile(r"\[DELEGATE:(\S+?)\](.+?)(?:\[/DELEGATE\]|$)", re.DOTALL)

redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(host="redis", port=6379, decode_responses=True)
    return redis_client


def extract_delegations(content: str) -> list[tuple[str, str]]:
    return DELEGATE_PATTERN.findall(content)


def strip_delegations(content: str) -> str:
    return DELEGATE_PATTERN.sub("", content).strip()


async def publish_event(channel: str, event: dict):
    r = await get_redis()
    await r.publish(channel, json.dumps(event))


async def enqueue_task(task: dict):
    r = await get_redis()
    await r.rpush("ai:tasks", json.dumps(task))


async def dequeue_task() -> dict | None:
    r = await get_redis()
    result = await r.lpop("ai:tasks")
    if result:
        return json.loads(result)
    return None
