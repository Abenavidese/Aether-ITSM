"""
Builds evals/rag/corpus/main/manual_impresoras.pdf — the PDF case of the RAG
eval corpus: headings in a larger font, a bordered table (printer per floor),
a section that continues across a page break, and a last page with no text
layer (what a scanned page looks like to a parser).

Written by hand (raw PDF operators) so the fixture is reproducible without a
PDF library: `python -m evals.rag.build_pdf`.
"""
from pathlib import Path

OUT = Path(__file__).parent / "corpus" / "main" / "manual_impresoras.pdf"
PAGE_W, PAGE_H = 595, 842


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Page:
    def __init__(self):
        self.ops: list[str] = []
        self.y = PAGE_H - 70

    def text(self, s: str, size: int = 10, x: int = 60, gap: int | None = None) -> None:
        self.ops.append(f"BT /F1 {size} Tf {x} {self.y} Td ({_esc(s)}) Tj ET")
        self.y -= gap if gap is not None else int(size * 1.6)

    def heading(self, s: str) -> None:
        self.y -= 8
        self.text(s, size=15, gap=26)

    def table(self, rows: list[list[str]], widths: list[int], x: int = 60, row_h: int = 20) -> None:
        top = self.y + 14
        total_w = sum(widths)
        for r, row in enumerate(rows):
            y_line = top - r * row_h
            self.ops.append(f"{x} {y_line} m {x + total_w} {y_line} l S")
            cx = x
            for w, cell in zip(widths, row, strict=True):
                self.ops.append(f"BT /F1 10 Tf {cx + 5} {y_line - 14} Td ({_esc(cell)}) Tj ET")
                cx += w
        bottom = top - len(rows) * row_h
        self.ops.append(f"{x} {bottom} m {x + total_w} {bottom} l S")
        cx = x
        for w in [0] + widths:
            cx += w
            self.ops.append(f"{cx} {top} m {cx} {bottom} l S")
        self.y = bottom - 24


def build() -> bytes:
    p1, p2, p3 = Page(), Page(), Page()
    p1.text("Manual de impresoras de oficina - Andina Logistica", size=18, gap=34)
    p1.heading("Impresoras por piso")
    p1.text("Cada piso tiene una impresora multifuncion. Use la cola de su piso.")
    p1.text("Las impresoras se agregan solas en equipos del dominio.", gap=30)
    p1.table([
        ["Piso", "Modelo", "Direccion IP", "Cola"],
        ["1", "HP LaserJet M507", "10.20.1.15", "IMP-P1-RECEPCION"],
        ["2", "Ricoh IM C3000", "10.20.2.15", "IMP-P2-FINANZAS"],
        ["3", "Ricoh IM C3000", "10.20.3.15", "IMP-P3-OPERACIONES"],
        ["4", "HP LaserJet M507", "10.20.4.15", "IMP-P4-TECNOLOGIA"],
    ], [50, 150, 110, 170])
    p1.heading("Codigos de error de las impresoras")
    p1.text("E-05: atasco de papel en la bandeja 2. Abra la puerta lateral derecha")
    p1.text("y retire el papel tirando hacia usted, sin girar los rodillos.")
    # The section continues on the next page (a chunker that splits per page cuts it).
    p2.text("E-12: toner agotado. El toner de repuesto esta en el armario de cada piso;")
    p2.text("si no hay, pida uno por ticket de categoria Hardware indicando el piso.")
    p2.text("E-31: error de red. Verifique que el cable este conectado y que la IP")
    p2.text("de la impresora responda. Si no responde, abra un ticket.", gap=30)
    p2.heading("Impresion segura")
    p2.text("Los documentos confidenciales se imprimen con retencion: el trabajo queda")
    p2.text("en la impresora hasta que el usuario acerca su credencial al lector.")
    p2.text("Los trabajos retenidos se borran solos a las 24 horas.")
    # p3: no text operators at all — a "scanned" page.
    p3.ops.append("0.9 g 60 400 475 300 re f 0 g")

    objects: list[bytes] = []
    pages = [p1, p2, p3]
    font_id = 3
    page_ids = []
    body = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,  # pages tree, filled below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for page in pages:
        stream = "\n".join(page.ops).encode("latin-1")
        content_id = len(body) + 1
        body.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_id = len(body) + 1
        page_ids.append(page_id)
        body.append((
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode())
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    body[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(body, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(body) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(body) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    objects.append(bytes(out))
    return objects[0]


if __name__ == "__main__":
    OUT.write_bytes(build())
    print(f"wrote {OUT}")
