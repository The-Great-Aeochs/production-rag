"""Session manager for multi-turn conversations.

Stores conversation history in Redis with TTL-based expiry.
Handles rolling summarization when history gets too long.
"""

import json
import logging
import time
import uuid

import redis

from shared.config import settings
from shared.models import ConversationMessage

log = logging.getLogger(__name__)


def create_session(client: redis.Redis) -> str:
    """Create a new session and return its ID."""
    session_id = uuid.uuid4().hex[:16]
    key = f"session:{session_id}:meta"
    client.hset(key, mapping={
        "created_at": str(time.time()),
        "last_active": str(time.time()),
        "message_count": "0",
    })
    client.expire(key, settings.session_ttl)
    return session_id


def add_message(
    session_id: str,
    message: ConversationMessage,
    client: redis.Redis,
) -> None:
    """Append a message to the session history."""
    msg_key = f"session:{session_id}:messages"
    meta_key = f"session:{session_id}:meta"

    msg_data = json.dumps({
        "role": message.role,
        "content": message.content,
        "token_count": message.token_count,
        "timestamp": time.time(),
    })
    client.rpush(msg_key, msg_data)
    client.hset(meta_key, "last_active", str(time.time()))
    client.hincrby(meta_key, "message_count", 1)

    # Refresh TTL on both keys
    client.expire(msg_key, settings.session_ttl)
    client.expire(meta_key, settings.session_ttl)


def get_recent_messages(
    session_id: str,
    client: redis.Redis,
    max_messages: int | None = None,
) -> list[ConversationMessage]:
    """Load recent messages from session history."""
    msg_key = f"session:{session_id}:messages"
    limit = max_messages or settings.session_max_history

    # Get the last N messages
    raw = client.lrange(msg_key, -limit, -1)
    messages = []
    for item in raw:
        data = json.loads(item)
        messages.append(ConversationMessage(
            role=data["role"],
            content=data["content"],
            token_count=data.get("token_count", 0),
        ))
    return messages


def get_summary(session_id: str, client: redis.Redis) -> str | None:
    """Get the rolling conversation summary, if any."""
    key = f"session:{session_id}:summary"
    return client.get(key)


def set_summary(session_id: str, summary: str, client: redis.Redis) -> None:
    """Store the rolling conversation summary."""
    key = f"session:{session_id}:summary"
    client.set(key, summary, ex=settings.session_ttl)


def trim_old_messages(session_id: str, keep: int, client: redis.Redis) -> None:
    """Remove oldest messages beyond the keep limit."""
    msg_key = f"session:{session_id}:messages"
    total = client.llen(msg_key)
    if total > keep:
        client.ltrim(msg_key, total - keep, -1)


def session_exists(session_id: str, client: redis.Redis) -> bool:
    """Check if a session exists."""
    return client.exists(f"session:{session_id}:meta") > 0


def total_history_tokens(messages: list[ConversationMessage]) -> int:
    """Sum token counts across all messages."""
    return sum(m.token_count for m in messages)
