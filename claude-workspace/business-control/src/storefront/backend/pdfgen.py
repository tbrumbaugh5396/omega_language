"""Markdown documents as PDFs, from the same parse the sign page renders.

One parser (documents.md_blocks) feeds both the HTML a signer is shown and
the bytes generated here, so the two can never carry different readings of
the same document. fpdf2 is pure Python — no cairo, no system packages —
which is what lets this run on the same laptop that runs everything else.

Core Helvetica only speaks latin-1, and the kit's documents are full of em
dashes, curly quotes and checkboxes — so text passes through a small
downcast first. An unmapped character becomes '?', never an exception: a
client asking for their proposal must always get a proposal.
"""
import re

from fpdf import FPDF

from . import documents as vault

# Characters the kit actually uses that latin-1 lacks.
_DOWNCAST = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    "☐": "[ ]", "☑": "[x]", "☒": "[x]", "✓": "x",
    "✕": "x", "✗": "x", "→": "->", "←": "<-",
    "·": "-", "★": "*", "☆": "*", " ": " ",
    "≤": "<=", "≥": ">=", "−": "-",
}


def _latin(text: str) -> str:
    for k, v in _DOWNCAST.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*)\)")


def _inline(text: str) -> str:
    """To fpdf's own markdown flavour: **bold** stays, *em* becomes
    __italic__, code ticks drop, links keep their text and show an external
    URL beside it. Signing markers become the labelled lines DocuSign
    anchors on — the label text must match documents.SIGN_MARKERS exactly,
    since the PDF is what the anchor search reads."""
    t = text
    t = t.replace("[SIGN HERE]", "**Sign here:** ____________________")
    t = t.replace("[INITIALS]", "**Initials:** ________")
    t = _LINK.sub(lambda m: m.group(1) if m.group(2).startswith("/")
                  else f"{m.group(1)} ({m.group(2)})", t)
    t = re.sub(r"\[([^\]]+)\]\([\w./-]+\)", r"\1", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"__\1__", t)
    t = t.replace("`", "")
    return _latin(t)


INK = (27, 24, 31)
DIM = (93, 87, 104)
LINE = (233, 228, 220)


def _signature_block(pdf, sigs) -> None:
    """The signatures, on the document itself. A signed PDF that shows no
    signature reads as unsigned to everyone who wasn't in the audit trail —
    which is everyone the PDF gets forwarded to."""
    import base64
    import io
    import time as _t

    pdf.ln(6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 13)
    pdf.multi_cell(0, 6.5, "Signed")
    pdf.ln(1)
    for s in sigs:
        drawn = (s.get("signature_data") or "")
        if drawn.startswith("data:image/png;base64,"):
            try:
                img = io.BytesIO(base64.b64decode(drawn.split(",", 1)[1]))
                pdf.image(img, w=52)
            except Exception:
                drawn = ""          # a broken mark falls back to the name
        if not drawn.startswith("data:image/png;base64,"):
            # the typed name, set apart so it reads as a mark, not as text
            pdf.set_font("helvetica", "I", 15)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 8, _latin(s.get("typed_name")
                                        or s.get("signer_name") or ""))
        # multi_cell parks the cursor at the right edge; every full-width
        # line that follows must walk back to the margin first
        pdf.set_font("helvetica", "B", 10.5)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5.4, _latin(s.get("signer_name") or ""))
        pdf.set_font("helvetica", size=9)
        pdf.set_text_color(*DIM)
        pdf.set_x(pdf.l_margin)
        when = s.get("signed_at") or 0
        line = f"{s.get('signer_email', '')} - {s.get('role', 'signer')}"
        if when:
            line += " - signed " + _t.strftime("%d %b %Y %H:%M UTC",
                                               _t.gmtime(when))
        if s.get("provider") and s.get("provider") != "builtin":
            line += f" - via {s['provider']}"
        pdf.multi_cell(0, 4.8, _latin(line))
        ref = (s.get("token") or "")[:12]
        sha = (s.get("doc_sha256") or "")[:16]
        if ref or sha:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 4.8, _latin(
                f"reference {ref}" + (f" - document sha256 {sha}..."
                                      if sha else "")))
        pdf.set_text_color(*INK)
        pdf.ln(3)


def _pending_block(pdf, pending) -> None:
    """Blank signature areas for the signers who haven't yet — so the PDF
    prints as a form: a line to sign on, a line to date, the name beneath.
    The paper comes back as a scan, uploaded beside the document."""
    pdf.ln(6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 13)
    pdf.multi_cell(0, 6.5, "Signatures")
    pdf.set_font("helvetica", size=9)
    pdf.set_text_color(*DIM)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 4.8, "Awaiting signature - sign electronically from "
                           "the emailed link, or sign this printed copy and "
                           "return a scan.")
    pdf.set_text_color(*INK)
    pdf.ln(4)
    for s in pending:
        y = pdf.get_y()
        if y > pdf.h - 55:
            pdf.add_page()
            y = pdf.get_y()
        half = (pdf.w - pdf.l_margin - pdf.r_margin - 14) / 2
        pdf.line(pdf.l_margin, y + 14, pdf.l_margin + half, y + 14)
        pdf.line(pdf.l_margin + half + 14, y + 14,
                 pdf.w - pdf.r_margin, y + 14)
        pdf.set_y(y + 15.5)
        pdf.set_font("helvetica", "B", 9.5)
        pdf.set_x(pdf.l_margin)
        pdf.cell(half, 4.8, _latin(s.get("signer_name") or "Signature"))
        pdf.set_x(pdf.l_margin + half + 14)
        pdf.cell(half, 4.8, "Date")
        pdf.ln(6)
        pdf.set_font("helvetica", size=8.5)
        pdf.set_text_color(*DIM)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 4.2, _latin(
            f"{s.get('signer_email', '')} - {s.get('role', 'signer')}"))
        pdf.set_text_color(*INK)
        pdf.ln(5)


def _new_pdf() -> FPDF:
    pdf = FPDF(format="letter")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, margin=18)
    return pdf


def _render_into(pdf: FPDF, title: str, md_text: str,
                 signatures: list | None, pending: list | None) -> None:
    """One document onto the current page of an open PDF — the single
    renderer behind a standalone PDF and a binder page alike."""
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*LINE)

    pdf.set_font("helvetica", "B", 19)
    pdf.multi_cell(0, 8.5, _latin(title))
    pdf.ln(3)

    blocks = vault.md_blocks(md_text)
    # The body usually repeats the title as its own first heading; printing
    # it twice reads like a stutter.
    if blocks and blocks[0][0] == "h" and blocks[0][1] == 1 \
            and _latin(blocks[0][2]).strip() == _latin(title).strip():
        blocks = blocks[1:]

    for b in blocks:
        kind = b[0]
        if kind == "h":
            size = {1: 15, 2: 13, 3: 11.5}.get(b[1], 11)
            pdf.ln(2.5)
            pdf.set_font("helvetica", "B", size)
            pdf.multi_cell(0, size * 0.5, _latin(b[2]))
            pdf.ln(1)
        elif kind == "hr":
            pdf.ln(2)
            pdf.line(pdf.l_margin, pdf.get_y(),
                     pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(3)
        elif kind == "aline":
            # a write-in line: lower and lighter than a section rule, so a
            # printed questionnaire reads as a form, not a page of dividers
            pdf.ln(6)
            pdf.set_draw_color(*DIM)
            pdf.line(pdf.l_margin, pdf.get_y(),
                     pdf.w - pdf.r_margin, pdf.get_y())
            pdf.set_draw_color(*LINE)
            pdf.ln(5)
        elif kind == "table":
            pdf.set_font("helvetica", size=9)
            with pdf.table(line_height=5.2,
                           borders_layout="HORIZONTAL_LINES",
                           text_align="LEFT", padding=1.2,
                           markdown=True) as table:
                head = table.row()
                for cell in b[1]:
                    head.cell(_inline(cell))
                for r in b[2]:
                    row = table.row()
                    # a ragged row still lays out; a crash never does
                    for j in range(len(b[1])):
                        row.cell(_inline(r[j]) if j < len(r) else "")
            pdf.ln(2)
        elif kind == "list":
            pdf.set_font("helvetica", size=10.5)
            for n, item in enumerate(b[2], 1):
                marker = f"{n}." if b[1] else "-"
                y0 = pdf.get_y()
                pdf.set_x(pdf.l_margin + 2)
                pdf.cell(6, 5.6, marker)
                pdf.set_xy(pdf.l_margin + 8, y0)
                pdf.multi_cell(0, 5.6, _inline(item), markdown=True)
            pdf.ln(1.5)
        elif kind == "quote":
            pdf.set_font("helvetica", "I", 10)
            pdf.set_text_color(*DIM)
            x0, y0 = pdf.l_margin + 4, pdf.get_y()
            pdf.set_x(x0)
            pdf.multi_cell(0, 5.4, _inline(b[1]), markdown=True)
            pdf.set_draw_color(*DIM)
            pdf.line(pdf.l_margin + 1, y0, pdf.l_margin + 1, pdf.get_y())
            pdf.set_draw_color(*LINE)
            pdf.set_text_color(*INK)
            pdf.ln(2)
        else:
            pdf.set_font("helvetica", size=10.5)
            pdf.multi_cell(0, 5.6, _inline(b[1]), markdown=True)
            pdf.ln(1.5)

    if signatures:
        _signature_block(pdf, signatures)
    if pending:
        _pending_block(pdf, pending)


def doc_pdf(title: str, md_text: str, signatures: list | None = None,
            pending: list | None = None) -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    _render_into(pdf, title, md_text, signatures, pending)
    return bytes(pdf.output())


def binder_pdf(sections: list) -> bytes:
    """All the paperwork as one book: each section — a document with its
    signatures and its blanks-to-sign — starts on a fresh page, in the
    order the process runs. sections: [{title, body, signatures, pending}]"""
    pdf = _new_pdf()
    for sec in sections:
        pdf.add_page()
        _render_into(pdf, sec["title"], sec["body"],
                     sec.get("signatures"), sec.get("pending"))
    return bytes(pdf.output())
