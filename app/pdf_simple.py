"""A very small PDF writer for plain text documents (no extra library needed).

It only does what the doctor summary needs: A4 pages, a title, headings,
wrapped text lines, thin rules and page numbers, using the built-in
Helvetica fonts. Text is written uncompressed, so tests can search it.
"""
import textwrap
import unicodedata

PAGE_W, PAGE_H = 595, 842          # A4 in points
MARGIN_X, TOP, BOTTOM = 56, 790, 64

STYLES = {
    #        font, size, line height, colour (r g b), space before
    "title": ("F2", 18, 24, (0.07, 0.19, 0.18), 0),
    "banner": ("F2", 9, 13, (0.54, 0.35, 0.0), 2),
    "h2": ("F2", 12, 17, (0.06, 0.37, 0.35), 12),
    "text": ("F1", 10, 14, (0.11, 0.12, 0.12), 0),
    "label": ("F2", 10, 14, (0.11, 0.12, 0.12), 0),
    "small": ("F1", 8.5, 12, (0.4, 0.45, 0.44), 0),
}


def _to_latin(text: str) -> bytes:
    """PDF built-in fonts use Windows-1252. Turn other letters (like the macron in Whanau) into plain ones."""
    out = []
    for ch in str(text):
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            plain = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append(plain if plain and all(ord(c) < 128 for c in plain) else "?")
    return "".join(out).encode("cp1252")


def _escape(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _wrap(text: str, size: float, indent: float) -> list[str]:
    # Helvetica is about half as wide as it is tall on average
    width_chars = max(20, int((PAGE_W - 2 * MARGIN_X - indent) / (size * 0.5)))
    lines = []
    for paragraph in str(text).split("\n"):
        lines.extend(textwrap.wrap(paragraph, width_chars) or [""])
    return lines


def make_pdf(blocks: list[tuple], footer: str = "") -> bytes:
    """blocks: (style, text) or (style, text, indent) or ("rule",). Returns the PDF file as bytes."""
    pages: list[list[bytes]] = [[]]
    y = TOP

    def new_page():
        nonlocal y
        pages.append([])
        y = TOP

    for block in blocks:
        if block[0] == "rule":
            if y - 10 < BOTTOM:
                new_page()
            y -= 6
            pages[-1].append(f"0.85 0.84 0.82 RG 0.6 w {MARGIN_X} {y} m {PAGE_W - MARGIN_X} {y} l S".encode())
            y -= 8
            continue
        style, text = block[0], block[1]
        indent = block[2] if len(block) > 2 else 0
        font, size, lead, (r, g, b), before = STYLES[style]
        y -= before
        for line in _wrap(text, size, indent):
            if y - lead < BOTTOM:
                new_page()
            y -= lead
            pages[-1].append(
                b"BT /" + font.encode() + f" {size} Tf {r} {g} {b} rg {MARGIN_X + indent} {y} Td (".encode()
                + _escape(_to_latin(line)) + b") Tj ET"
            )

    total = len(pages)
    for number, ops in enumerate(pages, start=1):
        note = f"{footer}   Page {number} of {total}".strip()
        ops.append(b"BT /F1 8 Tf 0.45 0.5 0.49 rg " + f"{MARGIN_X} 36 Td (".encode() + _escape(_to_latin(note)) + b") Tj ET")

    # Objects: 1 catalog, 2 page list, 3 and 4 fonts, then a page and its content for each page
    objects: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for ops in pages:
        stream = b"\n".join(ops)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
