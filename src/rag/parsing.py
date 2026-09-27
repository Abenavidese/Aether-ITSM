"""
Turns an uploaded file into plain text for chunking (Fase 14.6).

PDFs are parsed with pdfplumber instead of a flat text dump, because the
flat dump loses exactly what retrieval needs:
- headings: a line set noticeably larger than the body text becomes a
  Markdown heading, so the chunker (src/rag/chunking.py) can split by
  section and label each chunk — a flat dump gave every PDF chunk an empty
  section;
- tables: extracted as Markdown tables (header row + one line per row), not
  as words run together;
- pages without a text layer (scanned) are reported instead of silently
  indexed as nothing. OCR is out of scope (Planned).

Pure over a local file path; no database, no embeddings.
"""
import statistics
from dataclasses import dataclass, field
from pathlib import Path

HEADING_SIZE_RATIO = 1.2
_MAX_HEADING_CHARS = 120
_MIN_PAGE_CHARS = 20


class DocumentParseError(Exception):
    """The file can't produce any indexable text (reported to the uploader)."""


@dataclass
class ParsedDocument:
    text: str
    pages: int | None = None
    page_offsets: list[tuple[int, int]] | None = None   # (char offset in text, page number)
    warnings: list[str] = field(default_factory=list)


def parse_file(path: str | Path) -> ParsedDocument:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    text = path.read_bytes().decode("utf-8-sig")
    if not text.strip():
        raise DocumentParseError("The document has no text.")
    return ParsedDocument(text=text)


def _markdown_table(rows: list[list[str | None]]) -> str:
    def cell(value: str | None) -> str:
        return " ".join((value or "").split()).replace("|", "\\|")

    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = []
    for i, row in enumerate(rows):
        cells = [cell(c) for c in row] + [""] * (width - len(row))
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + "---|" * width)
    return "\n".join(lines)


def _inside(obj: dict, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    return obj["x0"] >= x0 - 1 and obj["x1"] <= x1 + 1 and obj["top"] >= top - 1 and obj["bottom"] <= bottom + 1


def _body_font_size(pdf) -> float:
    sizes = [round(c["size"], 1) for page in pdf.pages for c in page.chars if c.get("text", "").strip()]
    return statistics.median(sizes) if sizes else 0.0


def _page_blocks(page, body_size: float, title_size: float | None) -> list[tuple[float, str]]:
    tables = page.find_tables()
    bboxes = [t.bbox for t in tables]
    blocks: list[tuple[float, str]] = []
    for table in tables:
        markdown = _markdown_table(table.extract())
        if markdown:
            blocks.append((table.bbox[1], f"\n{markdown}\n"))

    text_only = page.filter(lambda obj: obj.get("object_type") != "char" or not any(_inside(obj, b) for b in bboxes))
    for line in text_only.extract_text_lines(strip=True, return_chars=True):
        text = line["text"].strip()
        if not text:
            continue
        sizes = [c["size"] for c in line["chars"] if c.get("text", "").strip()]
        size = statistics.mean(sizes) if sizes else body_size
        is_heading = (body_size and size >= body_size * HEADING_SIZE_RATIO
                      and len(text) <= _MAX_HEADING_CHARS and not text.endswith((".", ",", ";", ":")))
        if is_heading:
            marker = "#" if title_size and size >= title_size else "##"
            blocks.append((line["top"], f"\n{marker} {text}\n"))
        else:
            blocks.append((line["top"], text))
    return sorted(blocks, key=lambda b: b[0])


def parse_pdf(path: Path) -> ParsedDocument:
    import pdfplumber

    parts, offsets, warnings, offset = [], [], [], 0
    with pdfplumber.open(str(path)) as pdf:
        body_size = _body_font_size(pdf)
        first_sizes = [c["size"] for c in pdf.pages[0].chars if c.get("text", "").strip()] if pdf.pages else []
        # The largest text on the first page, if clearly above headings, is the document title.
        title_size = max(first_sizes) if first_sizes and max(first_sizes) >= body_size * 1.6 else None
        empty_pages = []
        for number, page in enumerate(pdf.pages, start=1):
            page_text = "\n".join(text for _, text in _page_blocks(page, body_size, title_size)).strip()
            if len(page_text) < _MIN_PAGE_CHARS:
                empty_pages.append(number)
            offsets.append((offset, number))
            parts.append(page_text)
            offset += len(page_text) + 2  # the "\n\n" joiner below
        page_count = len(pdf.pages)

    if empty_pages:
        warnings.append(f"Páginas sin texto extraíble (¿escaneadas?): {', '.join(map(str, empty_pages))}. "
                        "Su contenido no se indexó (OCR no disponible).")
    text = "\n\n".join(parts)
    if not text.strip():
        raise DocumentParseError("The PDF has no extractable text (scanned images only?). OCR is not supported.")
    return ParsedDocument(text=text, pages=page_count, page_offsets=offsets, warnings=warnings)
