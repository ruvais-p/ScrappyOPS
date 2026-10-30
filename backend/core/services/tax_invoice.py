"""The tax invoice PDF for the two kinds of invoice (a franchise's invoice to HQ, and HQ's invoice to a buyer). Same look as the
franchise module's invoice. Amounts are written "Rs." because the standard PDF fonts have no rupee sign."""
import io
import re
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.models import Invoice
from core.services.common import fetch
from core.services.invoice import clean, in_words, money

BLUE, BLUE_DARK, WASH, LINE = colors.HexColor("#0b82a7"), colors.HexColor("#087396"), colors.HexColor("#edf6f9"), colors.HexColor("#cbdde4")
INK, MUTED, RED = colors.HexColor("#252f34"), colors.HexColor("#52666d"), colors.HexColor("#b3261e")
LOGO = Path(__file__).resolve().parents[2] / "kwd" / "static" / "kwd" / "brand" / "scrappy-innovation.jpeg"
WIDTH = A4[0] - 30 * mm


def _style(name, size=8.5, bold=False, color=INK, align=0, leading=None):
    return ParagraphStyle(name, fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=leading or size * 1.35, textColor=color, alignment=align)


BODY, BOLD, RIGHT, CENTER = _style("body"), _style("bold", bold=True), _style("right", align=2), _style("center", align=1)
HEAD, HEAD_R, HEAD_C = _style("head", 7.2, True, colors.white), _style("headr", 7.2, True, colors.white, 2), _style("headc", 7.2, True, colors.white, 1)
SMALL, SMALL_R = _style("small", 8), _style("smallr", 8, align=2)


def rs(n):
    return "Rs. " + money(n or 0)


def p(text, style=BODY):
    return Paragraph(escape(clean(text)), style)


def lines_of(value):
    return "<br/>".join(escape(clean(x)) for x in str(value or "").splitlines() if clean(x))


def file_name(inv):
    return "Invoice-" + (re.sub(r"[^A-Za-z0-9._-]+", "-", inv.code) or str(inv.pk)).strip("-") + ".pdf"


def parties(inv):
    """(seller, buyer) details as dicts with name, address, phone, email, gstin, state."""
    return inv.seller_details, inv.buyer_details


def build(invoice_id):
    inv = Invoice.objects.get(pk=invoice_id)
    seller, buyer = parties(inv)
    lines = fetch("""select l.item_name, l.hsn_code, l.kg, l.rate, l.gst_percent, l.taxable, l.gst_amount, l.total
                     from invoice_lines l join scrap_items i on i.id = l.item_id where l.invoice_id = %(i)s order by l.id""", {"i": inv.pk})
    load = fetch("select code from hq_dispatches where id = %(d)s", {"d": inv.dispatch_id})[0]["code"] if inv.dispatch_id else None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {inv.code}", author=clean(seller["name"]))
    story = []

    band = Table([[Paragraph("TAX INVOICE", _style("band", 16, True, colors.white))]], colWidths=[116 * mm], rowHeights=[17 * mm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    logo = ""
    if LOGO.exists():
        w, h = ImageReader(str(LOGO)).getSize()
        lw = min(58 * mm, 24 * mm * w / h)
        logo = Image(str(LOGO), width=lw, height=lw * h / w, hAlign="RIGHT")
    top = Table([[band, logo]], colWidths=[116 * mm, WIDTH - 116 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top, Spacer(1, 3 * mm), Paragraph(escape(clean(seller["name"])), _style("seller", 13, True)), Spacer(1, 2 * mm)]

    def block(*pairs):
        return [Paragraph(f"<b>{escape(label)}</b><br/>{lines_of(value)}", _style("sb", 8, leading=11.5)) for label, value in pairs if clean(value)]
    cols = [block(("Address:", seller.get("address"))), block(("Phone:", seller.get("phone")), ("Email:", seller.get("email"))), block(("GSTIN:", seller.get("gstin")), ("State:", seller.get("state")))]
    grid = Table([[c or "" for c in cols]], colWidths=[WIDTH * .40, WIDTH * .30, WIDTH * .30])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 1.4, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [grid, Spacer(1, 4 * mm)]

    cancelled = inv.status == "cancelled"
    rows = [[p("Invoice No."), p(inv.code, BOLD)], [p("Date:"), p(inv.invoice_date.strftime("%d %b %Y") + ("  -  CANCELLED" if cancelled else ""), _style("dt", 8.5, cancelled, RED if cancelled else INK))]]
    if inv.vehicle_no:
        rows.append([p("Vehicle No."), p(inv.vehicle_no)])
    if load:
        rows.append([p("Load"), p(load)])
    left = Table(rows, colWidths=[28 * mm, 60 * mm])
    left.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    to_lines = [Paragraph("<b>Bill To:</b>", _style("bt", 9.5)), p(buyer["name"], BOLD)]
    if clean(buyer.get("address")):
        to_lines.append(Paragraph(lines_of(buyer["address"]), BODY))
    for label, key in (("GSTIN", "gstin"), ("State", "state"), ("Contact No.", "phone")):
        if clean(buyer.get(key)):
            to_lines.append(p(f"{label}: {buyer[key]}"))
    meta = Table([[left, to_lines]], colWidths=[WIDTH * .55, WIDTH * .45])
    meta.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, LINE), ("BACKGROUND", (1, 0), (1, 0), WASH), ("LINEBEFORE", (1, 0), (1, 0), .6, LINE),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [meta, Spacer(1, 5 * mm)]

    head = [("#", HEAD_C), ("Item name", HEAD), ("HSN", HEAD), ("Qty (kg)", HEAD_R), ("Rate/kg", HEAD_R), ("Taxable", HEAD_R), ("GST %", HEAD_C), ("GST", HEAD_R), ("Amount", HEAD_R)]
    table_rows = [[Paragraph(h, s) for h, s in head]]
    total_kg = Decimal(0)
    for n, ln in enumerate(lines, 1):
        total_kg += ln["kg"]
        table_rows.append([p(str(n), CENTER), p(ln["item_name"], SMALL), p(ln["hsn_code"] or "-", _style("hc", 8, align=1)), p(f"{ln['kg']:.3f}", SMALL_R), p(money(ln["rate"]), SMALL_R),
                           p(money(ln["taxable"]), SMALL_R), p(f"{ln['gst_percent'].normalize():f}%", _style("gc", 8, align=1)), p(money(ln["gst_amount"]), SMALL_R), p(money(ln["total"]), SMALL_R)])
    table_rows.append(["", p("Total", _style("tt", 8.5, True, BLUE_DARK)), "", p(f"{total_kg:.3f}", _style("tq", 8, True, BLUE_DARK, 2)), "", p(money(inv.subtotal), _style("t1", 8, True, BLUE_DARK, 2)), "",
                       p(money(inv.gst_total), _style("t2", 8, True, BLUE_DARK, 2)), p(money(inv.total), _style("t3", 8, True, BLUE_DARK, 2))])
    widths = [8 * mm, 40 * mm, 16 * mm, 18 * mm, 20 * mm, 24 * mm, 11 * mm, 19 * mm, 24 * mm]
    table = Table(table_rows, colWidths=widths, repeatRows=1)
    last = len(table_rows) - 1
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), .5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, last), (-1, last), WASH),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    story += [table, Spacer(1, 3 * mm)]

    paid = inv.payment_status == "paid"
    summary = [["Sub Total", rs(inv.subtotal)], ["GST", rs(inv.gst_total)], ["Total", rs(inv.total)],
               ["Payment", f"Paid on {inv.paid_on.strftime('%d %b %Y')}" + (f" ({inv.payment_ref})" if inv.payment_ref else "") if paid else "Not paid yet"],
               ["Balance", rs(0 if paid else inv.total)], ["Invoice Amount In Words", in_words(inv.total)]]
    srows = [[p(a), p(b, RIGHT if k < 5 else BODY)] for k, (a, b) in enumerate(summary)]
    srows[2] = [p("Total", _style("g1", 11, True, colors.white)), p(rs(inv.total), _style("g2", 11, True, colors.white, 2))]
    st = Table(srows, colWidths=[WIDTH * .52, WIDTH * .48])
    st.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, LINE), ("BACKGROUND", (0, 2), (-1, 2), BLUE), ("BACKGROUND", (0, 5), (-1, 5), WASH), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
    tail = [st]
    if inv.note:
        tail += [Spacer(1, 3 * mm), Paragraph(f"<b>Note:</b> {escape(clean(inv.note))}", _style("nt", 8, color=MUTED))]
    if cancelled and inv.cancel_reason:
        tail += [Spacer(1, 2 * mm), Paragraph(f"<b>Cancelled:</b> {escape(clean(inv.cancel_reason))}", _style("cn", 8, color=RED))]
    sign = Table([[""], [Paragraph(f"For {escape(clean(seller['name']))}<br/>Authorized Signatory", _style("sg", 8, color=MUTED, align=1))]], colWidths=[62 * mm], hAlign="RIGHT", rowHeights=[16 * mm, None])
    sign.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), .6, MUTED)]))
    story.append(KeepTogether(tail + [Spacer(1, 6 * mm), sign]))
    doc.build(story)
    return buf.getvalue(), file_name(inv)
