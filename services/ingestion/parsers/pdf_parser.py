"""Parse PDF files into structural sections using pymupdf.

Extracts text page by page. Attempts to detect section headers
via font size changes. Falls back to page-level sections if
no headers are detected.
"""

import pymupdf

from shared.models import Section


def parse_pdf(content: bytes, source_path: str) -> list[Section]:
    """Extract text from PDF, splitting on detected headers or pages."""
    doc = pymupdf.open(stream=content, filetype="pdf")
    sections: list[Section] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        page_sections = _extract_sections_from_blocks(blocks, page_num)
        if page_sections:
            sections.extend(page_sections)
        else:
            # Fallback: entire page as one section
            text = page.get_text().strip()
            if text:
                sections.append(Section(title=f"Page {page_num + 1}", content=text, level=0))

    doc.close()
    return sections


def _extract_sections_from_blocks(blocks: list[dict], page_num: int) -> list[Section]:
    """Try to split page blocks into sections based on font size."""
    # Collect all text spans with their font sizes
    spans: list[tuple[float, str]] = []
    for block in blocks:
        if block.get("type") != 0:  # text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    spans.append((span.get("size", 12.0), text))

    if not spans:
        return []

    # Find the median font size — anything significantly larger is a header
    sizes = sorted(s[0] for s in spans)
    median_size = sizes[len(sizes) // 2]
    header_threshold = median_size * 1.15

    sections: list[Section] = []
    current_title = f"Page {page_num + 1}"
    current_parts: list[str] = []

    for size, text in spans:
        if size >= header_threshold and len(text.split()) < 15:
            # Flush previous section
            if current_parts:
                body = " ".join(current_parts).strip()
                if body:
                    sections.append(Section(title=current_title, content=body, level=1))
                current_parts = []
            current_title = text
        else:
            current_parts.append(text)

    # Flush remaining
    if current_parts:
        body = " ".join(current_parts).strip()
        if body:
            sections.append(Section(title=current_title, content=body, level=1))

    return sections
