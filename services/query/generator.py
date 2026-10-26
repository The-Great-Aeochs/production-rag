"""LLM generation via Ollama HTTP API.

Builds a prompt from retrieved chunks and system instructions,
then calls Ollama for completion. Supports both full and streaming responses.
No LLM framework — plain HTTP calls.
"""

import asyncio
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
    remaining = settings.context_max_chars
    for i, chunk in enumerate(chunks, 1):
        section = " > ".join(chunk.section_path) if chunk.section_path else "general"
        header = f"[Context {i}] Source: {chunk.source_path}#{section}\n"
        if remaining <= len(header):
            break
        part = header + chunk.content[: remaining - len(header)]
        parts.append(part)
        remaining -= len(part) + 7
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
            messages.append(
                {
                    "role": "system",
                    "content": f"Conversation summary so far:\n{summary}",
                }
            )
        # Add recent exchanges (truncate long assistant responses)
        for msg in history:
            content = msg.content
            if msg.role == "assistant" and len(content) > 500:
                content = content[:500] + "..."
            messages.append({"role": msg.role, "content": content})

    # Current turn with retrieved context
    messages.append(
        {
            "role": "user",
            "content": f"/nothink\nContext:\n{context}\n\nQuestion: {query}",
        }
    )
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

    with httpx.Client(
        timeout=httpx.Timeout(settings.generation_timeout_s, connect=settings.dependency_timeout_s)
    ) as client:
        resp = client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": settings.generation_max_tokens},
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

    async with asyncio.timeout(settings.generation_timeout_s):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.generation_timeout_s,
                connect=settings.dependency_timeout_s,
            )
        ) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "stream": True,
                    "options": {"num_predict": settings.generation_max_tokens},
                },
            ) as resp:
                resp.raise_for_status()
                sanitizer = ThinkFilter()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise RuntimeError("Inference service returned a streaming error")
                    token = sanitizer.feed(data.get("message", {}).get("content", ""))
                    if token:
                        yield token
                    if data.get("done"):
                        tail = sanitizer.finish()
                        if tail:
                            yield tail
                        return
                raise RuntimeError("Inference stream ended without completion")


class ThinkFilter:
    """Remove reasoning tags even when tags are split across network tokens."""

    def __init__(self):
        self.buffer = ""
        self.hidden = False

    def feed(self, token: str) -> str:
        self.buffer += token
        output = []
        while self.buffer:
            marker = "</think>" if self.hidden else "<think>"
            position = self.buffer.find(marker)
            if position >= 0:
                if not self.hidden:
                    output.append(self.buffer[:position])
                self.buffer = self.buffer[position + len(marker) :]
                self.hidden = not self.hidden
                continue
            # Retain the longest suffix that could begin a split marker.
            keep = 0
            for size in range(1, min(len(marker), len(self.buffer) + 1)):
                if self.buffer.endswith(marker[:size]):
                    keep = size
            safe = self.buffer[:-keep] if keep else self.buffer
            if not self.hidden:
                output.append(safe)
            self.buffer = self.buffer[-keep:] if keep else ""
            break
        return "".join(output)

    def finish(self) -> str:
        # Drop incomplete tag prefixes to avoid leaking a partial <think>.
        self.buffer = ""
        return ""
