"""Parse Python source files into structural sections using tree-sitter.

Splits on top-level function and class definitions. Each function/class
becomes its own section. Module-level code (imports, constants, top-level
statements) is grouped into a preamble section.
"""

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from shared.models import Section

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)

# Node types that represent top-level structural boundaries
_BOUNDARY_TYPES = {"function_definition", "class_definition", "decorated_definition"}


def parse_python(content: str, source_path: str) -> list[Section]:
    """Split Python source into sections by function/class boundaries."""
    tree = _parser.parse(content.encode())
    root = tree.root_node
    sections: list[Section] = []

    preamble_parts: list[str] = []
    prev_end = 0

    for child in root.children:
        node_type = child.type

        # Collect gaps between structural nodes as preamble
        if node_type in _BOUNDARY_TYPES:
            gap = content[prev_end : child.start_byte].strip()
            if gap:
                preamble_parts.append(gap)

            # Extract the definition name
            name = _extract_name(child, content)
            body = content[child.start_byte : child.end_byte]

            sections.append(Section(title=name, content=body, level=1, language="python"))
            prev_end = child.end_byte
        else:
            # Non-structural node — accumulate as preamble
            preamble_parts.append(content[child.start_byte : child.end_byte])
            prev_end = child.end_byte

    # Trailing code after last definition
    trailing = content[prev_end:].strip()
    if trailing:
        preamble_parts.append(trailing)

    # Emit preamble section if non-empty
    preamble = "\n".join(preamble_parts).strip()
    if preamble:
        sections.insert(
            0,
            Section(
                title=f"{source_path} (module)",
                content=preamble,
                level=0,
                language="python",
            ),
        )

    return sections


def _extract_name(node, content: str) -> str:
    """Get the function/class name from a tree-sitter node."""
    # For decorated definitions, drill into the actual definition
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                node = child
                break

    for child in node.children:
        if child.type == "identifier":
            return content[child.start_byte : child.end_byte]

    return "unknown"
