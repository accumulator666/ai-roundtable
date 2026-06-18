"""
Cross-company communication via Redis pub/sub.
Companies can send messages, funding requests, and status updates to each other.
"""

import os
import json
import asyncio
import logging
from typing import Any, Callable, Optional
from datetime import datetime

import redis.asyncio as aioredis

logger = logging.getLogger("company_comms")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


# ============================================================
# Channel naming
# ============================================================

def company_channel(code: str) -> str:
    """Direct channel for a specific company."""
    return f"company:{code}:inbox"


def broadcast_channel() -> str:
    """Channel all companies listen on."""
    return "company:broadcast"


# ============================================================
# Sending messages
# ============================================================

async def send_to_company(target_code: str, message: dict, sender_code: str = "system"):
    """Send a message to a specific company's inbox."""
    r = await get_redis()
    envelope = {
        "from": sender_code,
        "to": target_code,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": message,
    }
    await r.publish(company_channel(target_code), json.dumps(envelope))
    logger.info(f"[{sender_code}] → [{target_code}]: {message.get('type', 'unknown')}")


async def broadcast(message: dict, sender_code: str = "system"):
    """Broadcast a message to all companies."""
    r = await get_redis()
    envelope = {
        "from": sender_code,
        "to": "all",
        "timestamp": datetime.utcnow().isoformat(),
        "payload": message,
    }
    await r.publish(broadcast_channel(), json.dumps(envelope))
    logger.info(f"[{sender_code}] → [broadcast]: {message.get('type', 'unknown')}")


# ============================================================
# Pre-built message types
# ============================================================

async def request_funding(from_code: str, amount: float, reason: str):
    """Send a funding request to MeshCapital (or holding if capital unavailable)."""
    await send_to_company("meshcapital", {
        "type": "funding_request",
        "amount": amount,
        "reason": reason,
    }, sender_code=from_code)


async def report_revenue(company_code: str, amount: float, source: str):
    """Report revenue to the holding company."""
    await send_to_company("holding", {
        "type": "revenue_report",
        "amount": amount,
        "source": source,
    }, sender_code=company_code)


async def strategic_directive(directive: str, target_code: str = "all"):
    """CEO sends a strategic directive to a company or all companies."""
    msg = {"type": "strategic_directive", "directive": directive}
    if target_code == "all":
        await broadcast(msg, sender_code="holding")
    else:
        await send_to_company(target_code, msg, sender_code="holding")


async def status_update(company_code: str, status: dict):
    """Company reports status to holding company."""
    await send_to_company("holding", {
        "type": "status_update",
        "status": status,
    }, sender_code=company_code)


# ============================================================
# Listening
# ============================================================

async def listen(company_code: str, callback: Callable[[dict], Any]):
    """
    Listen for messages on this company's inbox + broadcast channel.
    Runs forever — call as a background task.
    """
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(company_channel(company_code), broadcast_channel())
    logger.info(f"[{company_code}] Listening on {company_channel(company_code)} + {broadcast_channel()}")

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                envelope = json.loads(message["data"])
                # Don't process our own broadcasts
                if envelope.get("from") != company_code:
                    await callback(envelope)
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Error processing message: {e}")


# ============================================================
# Shared memory (Redis-backed key-value for cross-company state)
# ============================================================

async def set_shared(key: str, value: Any, company_code: str = "system"):
    """Set a shared key-value pair visible to all companies."""
    r = await get_redis()
    await r.set(f"shared:{key}", json.dumps({
        "value": value,
        "updated_by": company_code,
        "updated_at": datetime.utcnow().isoformat(),
    }))


async def get_shared(key: str) -> Optional[Any]:
    """Get a shared value."""
    r = await get_redis()
    raw = await r.get(f"shared:{key}")
    if raw:
        data = json.loads(raw)
        return data.get("value")
    return None
