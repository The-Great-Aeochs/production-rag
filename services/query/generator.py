"""LLM generation via Ollama HTTP API.

Builds a prompt from retrieved chunks and system instructions,
then calls Ollama for completion. Supports both full and streaming responses.
No LLM framework — plain HTTP calls.
"""

import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from shared.config import settings
from shared.models import ConversationMessage, RetrievalResult

log = logging.getLogger(__name__)

PROMPT_VERSION = "system_v1"
_system_prompt: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        path = Path(__file__).parent.parent.parent / "prompts" / "system_v1.txt"
        _system_prompt = path.read_text().strip()
    return _system_prompt


def _build_context(chunks: list[RetrievalResult]) -> str:
    """Format retrieved chunks as numbered context sections."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        section = " > ".join(chunk.section_path) if chunk.section_path else "general"
        parts.append(
            f"[Context {i}] Source: {chunk.source_path}#{section}\n{chunk.content}"
        )
    return "\n\n---\n\n".join(parts)


def _build_messages(
    query: str,
    chunks: list[RetrievalResult],
    history: list[ConversationMessage] | None = None,
    summary: str | None = None,
) -> list[dict]:
    """Build the chat messages for Ollama.

    If conversation history is provided, includes it so the LLM can
    maintain conversational coherence (tone, follow-ups, references).
    """
    context = _build_context(chunks)
    messages: list[dict] = [
        {"role": "system", "content": _get_system_prompt()},
    ]

    # Include conversation history for multi-turn context
    if history:
        # Add summary as a system-level context note if available
        if summary:
            messages.append({
                "role": "system",
                "content": f"Conversation summary so far:\n{summary}",
            })
        # Add recent exchanges (truncate long assistant responses)
        for msg in history:
            content = msg.content
            if msg.role == "assistant" and len(content) > 500:
                content = content[:500] + "..."
            messages.append({"role": msg.role, "content": content})

    # Current turn with retrieved context
    messages.append({
        "role": "user",
        "content": f"/nothink\nContext:\n{context}\n\nQuestion: {query}",
    })
    return messages


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks that Qwen3 emits despite /nothink."""
    return re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()


def generate(
    query: str,
    chunks: list[RetrievalResult],
    history: list[ConversationMessage] | None = None,
    summary: str | None = None,
) -> str:
    """Generate a full response from Ollama (non-streaming)."""
    messages = _build_messages(query, chunks, history, summary)

    with httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        resp = client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return _strip_think_tags(resp.json()["message"]["content"])


async def generate_stream(
    query: str,
    chunks: list[RetrievalResult],
    history: list[ConversationMessage] | None = None,
    summary: str | None = None,
) -> AsyncIterator[str]:
    """Stream response tokens from Ollama."""
    messages = _build_messages(query, chunks, history, summary)

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            in_think = False
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    buffer += token
                    # Skip everything inside <think>...</think>
                    if "<think>" in buffer and not in_think:
                        in_think = True
                    if in_think:
                        if "</think>" in buffer:
                            # Strip the think block and emit remainder
                            buffer = re.sub(r"<think>[\s\S]*?</think>\s*", "", buffer)
                            in_think = False
                            if buffer:
                                yield buffer
                                buffer = ""
                        continue
                    yield token
                    buffer = ""
                if data.get("done"):
                    break
