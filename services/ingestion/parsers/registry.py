"""Maps file extensions to their parser functions."""

from pathlib import Path

from shared.models import Section

from .code_parser import parse_python
from .markdown_parser import parse_markdown
from .pdf_parser import parse_pdf

# extension → (parser_func, doc_type, language)
_PARSERS: dict[str, tuple] = {
    ".md": (parse_markdown, "markdown", None),
    ".markdown": (parse_markdown, "markdown", None),
    ".py": (parse_python, "code", "python"),
}


def parse_file(path: Path) -> tuple[list[Section], str, str | None]:
    """Parse a file into sections based on its extension.

    Returns (sections, doc_type, language).
    For PDFs, reads bytes. For everything else, reads text.
    """
    ext = path.suffix.lower()

    if ext == ".pdf":
        raw = path.read_bytes()
        sections = parse_pdf(raw, str(path))
        return sections, "pdf", None

    if ext in _PARSERS:
        parser_fn, doc_type, language = _PARSERS[ext]
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = parser_fn(text, str(path))
        return sections, doc_type, language

    # Fallback: treat as plain text, one section
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = [Section(title=str(path), content=text, level=0)]
    return sections, "text", None


def supported_extensions() -> set[str]:
    """Return all file extensions we can parse."""
    return {".pdf"} | set(_PARSERS.keys())
