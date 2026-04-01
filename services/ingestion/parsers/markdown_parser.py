"""Parse markdown files into structural sections.

Splits on headers, preserving code blocks as their own sections
with language metadata. Non-heading content between headers is
grouped under the nearest preceding header.
"""

import re

from shared.models import Section

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def parse_markdown(content: str, source_path: str) -> list[Section]:
    """Split markdown into sections by headers, extracting code blocks."""
    sections: list[Section] = []

    # Find all header positions
    headers: list[tuple[int, int, str]] = []  # (pos, level, title)
    for m in _HEADER_RE.finditer(content):
        headers.append((m.start(), len(m.group(1)), m.group(2).strip()))

    if not headers:
        # No headers — treat entire document as one section
        sections.append(Section(title=source_path, content=content.strip(), level=0))
        return sections

    # Split content into header-delimited regions
    for i, (pos, level, title) in enumerate(headers):
        end = headers[i + 1][0] if i + 1 < len(headers) else len(content)
        body = content[pos:end]

        # Remove the header line itself from the body
        first_newline = body.find("\n")
        body = body[first_newline + 1 :] if first_newline != -1 else ""
        body = body.strip()

        if not body:
            continue

        # Extract code blocks as separate sections
        parts = _CODE_BLOCK_RE.split(body)
        # parts alternates: [text, lang, code, text, lang, code, ...]

        idx = 0
        while idx < len(parts):
            if idx + 2 < len(parts) and parts[idx + 1] is not None:
                # Check if this is a code block group (lang, code follow text)
                text_before = parts[idx].strip()
                if text_before:
                    sections.append(Section(title=title, content=text_before, level=level))

                lang = parts[idx + 1] or None
                code = parts[idx + 2].strip()
                if code:
                    sections.append(
                        Section(
                            title=f"{title} (code)",
                            content=code,
                            level=level,
                            language=lang,
                        )
                    )
                idx += 3
            else:
                text = parts[idx].strip()
                if text:
                    sections.append(Section(title=title, content=text, level=level))
                idx += 1

    return sections
