"""LLM generation via Ollama HTTP API.

Builds a prompt from retrieved chunks and system instructions,
then calls Ollama for completion. Supports both full and streaming responses.
No LLM framework — plain HTTP calls.
"""

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from shared.config import settings
from shared.models import RetrievalResult

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


def _build_messages(query: str, chunks: list[RetrievalResult]) -> list[dict]:
    """Build the chat messages for Ollama."""
    context = _build_context(chunks)
    return [
        {"role": "system", "content": _get_system_prompt()},
        {
            "role": "user",
            "content": f"/nothink\nContext:\n{context}\n\nQuestion: {query}",
        },
    ]


def generate(query: str, chunks: list[RetrievalResult]) -> str:
    """Generate a full response from Ollama (non-streaming)."""
    messages = _build_messages(query, chunks)

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def generate_stream(
    query: str, chunks: list[RetrievalResult]
) -> AsyncIterator[str]:
    """Stream response tokens from Ollama."""
    messages = _build_messages(query, chunks)

    async with httpx.AsyncClient(timeout=60.0) as client:
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
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break
