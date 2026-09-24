"""
Section-aware, contextual chunking for the RAG knowledge base.

Why this exists instead of a bare RecursiveCharacterTextSplitter:
- A fixed-size chunk loses WHAT it is about. "Requires manager approval, max
  30 days" means nothing once cut away from its "AWS IAM access" heading —
  the embedding can't place it and retrieval misses it. Every chunk here is
  prefixed with a short header (document + section) that is embedded AND
  shown to the LLM, so both the vector and the model know where it came from.
- Chunks never cross a section boundary: splitting happens per section, so a
  chunk can't be half "VPN policy" and half "MDM policy" (which blurs the
  embedding between two topics).
- Deterministic and LLM-free: headings are detected from the text's own
  formatting (Markdown "#", setext "----"/"====" underlines, or a short
  standalone line), so ingestion stays fast and $0 on local Ollama. An
  LLM-written per-chunk context ("contextual retrieval") is a possible later
  upgrade once ingestion runs against a hosted model.

Pure functions only (no I/O) — see src/rag/service.py for loading/storing.
"""
import re
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Bumped whenever chunk content/format changes, and stored on every chunk, so
# scripts/reindex_rag.py can find chunks produced by an older strategy.
CHUNKER_VERSION = "section-v1"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SETEXT_UNDERLINE = re.compile(r"^\s*(-{3,}|={3,})\s*$")
_LIST_MARKER = re.compile(r"^\s*([-*•]|\d+[.)])\s")
_MAX_HEADING_CHARS = 120
_MAX_HEADING_WORDS = 12


@dataclass(frozen=True)
class Section:
    title: str | None
    text: str
    start: int  # char offset of `text` within the full document


def _is_standalone_heading(line: str, prev_line: str | None, next_line: str | None) -> bool:
    """A short line on its own between blank lines, that reads like a title
    rather than a sentence or a list item ("Política de acceso a VPN")."""
    stripped = line.strip()
    if not stripped or line[:1].isspace():
        return False
    if prev_line is not None and prev_line.strip():
        return False
    if next_line is not None and next_line.strip():
        return False
    if len(stripped) > _MAX_HEADING_CHARS or len(stripped.split()) > _MAX_HEADING_WORDS:
        return False
    if _LIST_MARKER.match(line) or not any(c.isalpha() for c in stripped):
        return False
    # The document's first line is its title even when it ends in a period
    # ("... VERTEX DYNAMICS S.A.S."); anywhere else, sentence punctuation at
    # the end means prose, not a heading.
    return prev_line is None or stripped[-1] not in ".,;:!?"


def split_sections(text: str) -> list[Section]:
    """Splits `text` into (heading, body) sections by detected headings."""
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []  # (line_index, lines_consumed, title)

    for i, line in enumerate(lines):
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        md = _MARKDOWN_HEADING.match(line)
        if md:
            headings.append((i, 1, md.group(1).strip()))
        elif line.strip() and next_line is not None and _SETEXT_UNDERLINE.match(next_line) \
                and len(line.strip()) <= _MAX_HEADING_CHARS:
            headings.append((i, 2, line.strip()))

    # The "short standalone line" heuristic only applies to plain-text docs:
    # when a document marks its headings explicitly, that markup wins and a
    # one-line paragraph ("Gracias", "Ver anexo") stays body text.
    if not headings:
        for i, line in enumerate(lines):
            prev_line = lines[i - 1] if i > 0 else None
            next_line = lines[i + 1] if i + 1 < len(lines) else None
            if _is_standalone_heading(line, prev_line, next_line):
                headings.append((i, 1, line.strip()))

    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    sections: list[Section] = []
    first_start = headings[0][0] if headings else len(lines)
    if first_start > 0:
        body = "".join(lines[:first_start])
        if body.strip():
            sections.append(Section(None, body, 0))

    for n, (idx, consumed, title) in enumerate(headings):
        body_start = idx + consumed
        body_end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        # Headings with no body of their own (e.g. a document title directly
        # followed by the first section) still become sections: their title
        # is useful context, and an empty body produces no chunks anyway.
        sections.append(Section(title, "".join(lines[body_start:body_end]), offsets[body_start]))
    return sections


def _document_title(sections: list[Section]) -> str | None:
    # A heading at the very top with no body of its own is the document's
    # title ("GUÍA DE POLÍTICAS DE TI — VERTEX DYNAMICS S.A.S."), not a section.
    if sections and sections[0].title and not sections[0].text.strip():
        return sections[0].title
    return None


def build_header(filename: str, doc_title: str | None, section_title: str | None) -> str:
    document = f"{filename} — {doc_title}" if doc_title else filename
    header = f"Documento: {document}"
    if section_title and section_title != doc_title:
        header += f"\nSección: {section_title}"
    return header


def chunk_document(text: str, filename: str, base_metadata: dict | None = None,
                   page_offsets: list[tuple[int, int]] | None = None) -> list[Document]:
    """
    Turns a full document's text into contextual chunks ready to embed.

    `page_offsets` ([(char_offset, page_number), ...], ascending) lets PDF
    chunks keep the page they started on, even though pages are joined into
    one text first so sections (and chunks) can span a page break.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    sections = split_sections(text)
    doc_title = _document_title(sections)

    chunks: list[Document] = []
    for section in sections:
        if not section.text.strip():
            continue
        header = build_header(filename, doc_title, section.title)
        for piece in splitter.create_documents([section.text]):
            metadata = dict(base_metadata or {})
            metadata.update({
                "filename": filename,
                "section": section.title or "",
                "chunk_index": len(chunks),
                "chunker": CHUNKER_VERSION,
            })
            if page_offsets:
                absolute = section.start + piece.metadata.get("start_index", 0)
                metadata["page"] = max((p for off, p in page_offsets if off <= absolute), default=page_offsets[0][1])
            chunks.append(Document(page_content=f"{header}\n\n{piece.page_content.strip()}", metadata=metadata))
    return chunks
