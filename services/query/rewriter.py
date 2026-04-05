"""Context-aware query rewriter for multi-turn conversations.

Takes conversation history + the user's latest query and rewrites it
into a standalone search query. Handles coreference resolution,
ellipsis, and implicit context.

Uses a lightweight LLM call via Ollama. If rewriting fails or times out,
falls back to the raw query (graceful degradation).
"""

import logging
import re
from pathlib import Path

import httpx

from shared.config import settings
from shared.models import ConversationMessage

log = logging.getLogger(__name__)

_rewrite_prompt: str | None = None


def _get_rewrite_prompt() -> str:
    global _rewrite_prompt
    if _rewrite_prompt is None:
        path = Path(__file__).parent.parent.parent / "prompts" / "query_rewrite_v1.txt"
        _rewrite_prompt = path.read_text().strip()
    return _rewrite_prompt


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()


def _format_history(
    messages: list[ConversationMessage],
    summary: str | None = None,
) -> str:
    """Format conversation history for the rewrite prompt."""
    parts = []
    if summary:
        parts.append(f"Conversation summary:\n{summary}")
    if messages:
        parts.append("Recent exchanges:")
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            # Truncate long assistant responses for the rewriter
            content = msg.content
            if msg.role == "assistant" and len(content) > 300:
                content = content[:300] + "..."
            parts.append(f"  {role}: {content}")
    return "\n".join(parts)


def needs_rewrite(
    query: str,
    messages: list[ConversationMessage],
) -> bool:
    """Heuristic: does this query need rewriting?

    Skip rewriting for the first message or queries that appear
    self-contained (no pronouns, reasonable length).
    """
    if not messages:
        return False

    # Short queries with pronouns/demonstratives likely need rewriting
    pronoun_indicators = [
        "it", "its", "that", "this", "those", "these",
        "they", "them", "their", "he", "she",
        "the same", "above", "previous", "earlier",
        "more", "also", "too", "again",
    ]
    query_lower = query.lower()
    for indicator in pronoun_indicators:
        # Check as whole word
        if f" {indicator} " in f" {query_lower} ":
            return True

    # Very short queries in a conversation are almost always follow-ups
    if len(query.split()) <= 4 and len(messages) >= 2:
        return True

    return False


def rewrite_query(
    query: str,
    messages: list[ConversationMessage],
    summary: str | None = None,
) -> str:
    """Rewrite a follow-up query into a standalone search query.

    Returns the original query if rewriting fails or isn't needed.
    """
    if not needs_rewrite(query, messages):
        log.debug("Query appears self-contained, skipping rewrite")
        return query

    history = _format_history(messages, summary)
    system = _get_rewrite_prompt()
    user_content = f"/nothink\n{history}\n\nUser's latest question: {query}\n\nRewritten standalone query:"

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            resp = client.post(
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            rewritten = _strip_think_tags(resp.json()["message"]["content"]).strip()

            # Sanity check: rewritten query shouldn't be empty or way too long
            if not rewritten or len(rewritten) > len(query) * 5:
                log.warning("Rewriter produced suspicious output, using original query")
                return query

            log.info(f"Rewrote '{query}' -> '{rewritten}'")
            return rewritten

    except Exception as e:
        log.warning(f"Query rewrite failed, using original: {e}")
        return query
