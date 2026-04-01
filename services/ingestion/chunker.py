"""Structural chunker that respects document boundaries.

Takes parser sections and produces chunks within the configured
token range, with overlap for context continuity and parent-child
relationships for hierarchical retrieval.
"""

import hashlib
import uuid

import tiktoken

from shared.config import settings
from shared.models import Chunk, Section

_enc = tiktoken.get_encoding("cl100k_base")


_NAMESPACE = uuid.UUID("a3f1b2c4-d5e6-7890-abcd-ef1234567890")


def _make_id(key: str) -> str:
    """Deterministic UUID from a string key."""
    return str(uuid.uuid5(_NAMESPACE, key))


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def chunk_sections(
    sections: list[Section],
    source_path: str,
    doc_type: str,
    language: str | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Convert parsed sections into chunks with overlap and hierarchy."""
    doc_id = _make_id(source_path)
    meta = metadata or {}

    raw_chunks: list[dict] = []

    for section in sections:
        tokens = count_tokens(section.content)

        if tokens <= settings.chunk_max_tokens:
            raw_chunks.append(
                {
                    "content": section.content,
                    "token_count": tokens,
                    "section_title": section.title,
                    "level": section.level,
                    "language": section.language or language,
                }
            )
        else:
            # Split oversized sections on paragraph boundaries
            sub_chunks = _split_long_section(section, language)
            raw_chunks.extend(sub_chunks)

    # Merge undersized chunks with their neighbor
    merged = _merge_small_chunks(raw_chunks)

    # Build final Chunk objects with overlap and parent tracking
    chunks = _build_chunks(
        merged, doc_id, source_path, doc_type, language, meta
    )
    return chunks


def _split_long_section(section: Section, fallback_lang: str | None) -> list[dict]:
    """Split a section that exceeds max_tokens on paragraph boundaries."""
    paragraphs = section.content.split("\n\n")
    result: list[dict] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        if current_tokens + para_tokens > settings.chunk_max_tokens and current_parts:
            result.append(
                {
                    "content": "\n\n".join(current_parts),
                    "token_count": current_tokens,
                    "section_title": section.title,
                    "level": section.level,
                    "language": section.language or fallback_lang,
                }
            )
            current_parts = []
            current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        result.append(
            {
                "content": "\n\n".join(current_parts),
                "token_count": current_tokens,
                "section_title": section.title,
                "level": section.level,
                "language": section.language or fallback_lang,
            }
        )

    return result


def _merge_small_chunks(raw_chunks: list[dict]) -> list[dict]:
    """Merge adjacent chunks that are under min_tokens, if they share a parent."""
    if not raw_chunks:
        return []

    merged: list[dict] = [raw_chunks[0]]

    for chunk in raw_chunks[1:]:
        prev = merged[-1]
        can_merge = (
            prev["token_count"] < settings.chunk_min_tokens
            and prev["section_title"] == chunk["section_title"]
        )

        if can_merge:
            prev["content"] = prev["content"] + "\n\n" + chunk["content"]
            prev["token_count"] = count_tokens(prev["content"])
        else:
            merged.append(chunk)

    return merged


def _build_chunks(
    raw_chunks: list[dict],
    doc_id: str,
    source_path: str,
    doc_type: str,
    language: str | None,
    metadata: dict,
) -> list[Chunk]:
    """Assign IDs, overlap, section_path, and parent references."""
    chunks: list[Chunk] = []
    overlap_tokens = int(settings.chunk_max_tokens * settings.chunk_overlap_ratio)

    # Track section hierarchy for section_path
    section_stack: list[str] = []

    for i, raw in enumerate(raw_chunks):
        # Build section path from hierarchy
        title = raw["section_title"]
        level = raw["level"]

        # Trim stack to current level
        section_stack = section_stack[:level]
        if title and title not in section_stack:
            section_stack.append(title)

        # Add overlap from previous chunk
        content = raw["content"]
        if i > 0 and overlap_tokens > 0:
            prev_text = raw_chunks[i - 1]["content"]
            prev_tokens = _enc.encode(prev_text)
            overlap_text = _enc.decode(prev_tokens[-overlap_tokens:])
            content = overlap_text + "\n\n" + content

        chunk_id = _make_id(f"{source_path}:{i}")
        token_count = count_tokens(content)

        # Parent is the previous chunk at a higher level (lower number)
        parent_id = None
        if i > 0 and raw_chunks[i - 1]["level"] < level:
            parent_id = _make_id(f"{source_path}:{i - 1}")

        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=content,
                token_count=token_count,
                chunk_index=i,
                parent_chunk_id=parent_id,
                section_path=list(section_stack),
                source_path=source_path,
                doc_type=doc_type,
                language=raw.get("language") or language,
                metadata=metadata,
            )
        )

    return chunks
