"""The franchise tax invoice as a PDF file, laid out like the page the "Print invoice" button opens: title band and logo, seller
details, invoice number and bill-to, the items, the totals with the amount in words, and a signature line.
The standard PDF fonts have no rupee sign, so amounts are written "Rs. 1,23,456.00" (the same as the scrap app's bills)."""
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

from core.services.common import fetch, fetch_one
from core.services.invoice import clean, in_words, money

BLUE, BLUE_DARK, WASH, LINE = colors.HexColor("#0b82a7"), colors.HexColor("#087396"), colors.HexColor("#edf6f9"), colors.HexColor("#cbdde4")
INK, MUTED = colors.HexColor("#252f34"), colors.HexColor("#52666d")
LOGO = Path(__file__).resolve().parent / "static" / "kwd" / "brand" / "scrappy-innovation.jpeg"
SELLER = {
    "company_name": "SCRAPPY INNOVATIONS PVT LTD.",
    "address": "HO. WP 18/108 - H,J,K\n1st FLOOR SAJ BUILDING\nMANJERI ROAD WANDOOR\nPIN 679328",
    "phone": "+918592964750", "gstin": "32ABFCS0169R1ZX", "email": "info@scrappyinnovations.com", "state": "Kerala",
}
WIDTH = A4[0] - 30 * mm


def _style(name, size=8.5, bold=False, color=INK, align=0, leading=None):
    return ParagraphStyle(name, fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=leading or size * 1.35, textColor=color, alignment=align)


BODY, BOLD = _style("body"), _style("bold", bold=True)
HEAD = _style("head", 7.5, True, colors.white)
HEAD_R = _style("headr", 7.5, True, colors.white, 2)
HEAD_C = _style("headc", 7.5, True, colors.white, 1)
RIGHT, CENTER = _style("right", align=2), _style("center", align=1)


def rs(n):
    return "Rs. " + money(n or 0)


def p(text, style=BODY):
    return Paragraph(escape(clean(text)).replace("\n", "<br/>"), style)


def pretty_qty(n):
    n = Decimal(str(n or 0))
    return f"{n:.0f}" if n == n.to_integral() else f"{n:.2f}"


def file_name(sale):
    """Invoice numbers contain slashes (B2C/2627/1029/001); a file name cannot."""
    return "Invoice-" + (re.sub(r"[^A-Za-z0-9._-]+", "-", sale.get("invoice_no") or "") or str(sale["id"])[:8]).strip("-") + ".pdf"


def gather(sale):
    """Everything the invoice shows, read once the caller has been allowed to see the sale."""
    items = fetch("""select i.*, p.name as product_name, coalesce(p.unit, 'unit') as unit
                     from kwd_fr_sale_items i left join kwd_fr_products p on p.id = i.product_id
                     where i.sale_id = %(s)s order by i.id""", {"s": sale["id"]})
    company = fetch_one("select * from kwd_fr_company_settings where id = 1") or {}
    seller = {k: (company.get(k) or SELLER[k]) for k in SELLER}
    district = fetch_one("select name from kwd_districts where id = %(d)s", {"d": sale.get("district_id")}) if sale.get("district_id") else None
    return items, seller, (district or {}).get("name")


def build(sale, items, seller, district_name):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {sale.get('invoice_no') or ''}".strip(), author=clean(seller["company_name"]))
    story = []

    # title band and logo
    band = Table([[Paragraph("COMPANY BILLING &middot; TAX INVOICE", _style("band", 14, True, colors.white))]], colWidths=[116 * mm], rowHeights=[17 * mm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    logo = ""
    if LOGO.exists():
        w, h = ImageReader(str(LOGO)).getSize()
        lw = min(58 * mm, 24 * mm * w / h)
        logo = Image(str(LOGO), width=lw, height=lw * h / w, hAlign="RIGHT")
    top = Table([[band, logo]], colWidths=[116 * mm, WIDTH - 116 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top, Spacer(1, 3 * mm), Paragraph(escape(clean(seller["company_name"])), _style("seller", 13, True)), Spacer(1, 2 * mm)]

    # seller details
    def block(*pairs):
        def lines(value):
            return "<br/>".join(escape(clean(x)) for x in str(value).splitlines() if clean(x))
        return [Paragraph(f"<b>{escape(label)}</b><br/>{lines(value)}", _style("sb", 8, leading=11.5)) for label, value in pairs if value]
    cols = [block(("Address:", seller["address"])), block(("Phone:", seller["phone"]), ("Email:", seller["email"])), block(("GSTIN:", seller["gstin"]), ("State:", seller["state"]))]
    grid = Table([[c or "" for c in cols]], colWidths=[WIDTH * .40, WIDTH * .30, WIDTH * .30])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 1.4, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [grid, Spacer(1, 4 * mm)]

    # invoice number, date and who it is for
    sale_date = sale.get("sale_date")
    date_text = (sale_date.strftime("%d %b %Y") if hasattr(sale_date, "strftime") else str(sale_date or "-")) + (" - CANCELLED" if sale.get("status") == "cancelled" else "")
    left = Table([[p("Invoice No."), p(sale.get("invoice_no") or "-", BOLD)], [p("Date:"), p(date_text)]], colWidths=[28 * mm, 60 * mm])
    left.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    to_lines = [Paragraph("<b>Bill To:</b>", _style("bt", 9.5)), p(sale.get("customer_name") or "-"),
                p(", ".join(x for x in (sale.get("place"), district_name) if x) or "-")]
    if sale.get("phone"):
        to_lines.append(p(f"Contact No.: {sale['phone']}"))
    meta = Table([[left, to_lines]], colWidths=[WIDTH * .55, WIDTH * .45])
    meta.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, LINE), ("BACKGROUND", (1, 0), (1, 0), WASH), ("LINEBEFORE", (1, 0), (1, 0), .6, LINE),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [meta, Spacer(1, 5 * mm)]

    # the items
    rows = [[Paragraph(h, s) for h, s in (("#", HEAD_C), ("Item name", HEAD), ("HSN/SAC", HEAD), ("Quantity", HEAD_R), ("Unit", HEAD), ("Price/Unit", HEAD_R), ("GST", HEAD_C), ("Amount", HEAD_R))]]
    units, subtotal, gst_total = {}, Decimal(0), Decimal(0)
    for n, i in enumerate(items, 1):
        qty, line, gst = Decimal(str(i["qty"])), Decimal(str(i["line_total"] or 0)), Decimal(str(i.get("gst_amount") or 0))
        units[i["unit"]] = units.get(i["unit"], Decimal(0)) + qty
        subtotal, gst_total = subtotal + line, gst_total + gst
        rows.append([p(str(n), CENTER), p(i.get("product_name") or "Product"), p(i.get("hsn_sac") or "-", CENTER), p(f"{qty:.2f}", RIGHT), p(i["unit"]),
                     p(rs(i["unit_price"]), RIGHT), p(f"{Decimal(str(i.get('gst_percent') or 0)).normalize():f}%", CENTER), p(rs(line + gst), RIGHT)])
    qty_text = " | ".join(f"{pretty_qty(q)} {u}" for u, q in units.items()) or "-"
    if not items:
        rows.append([p("No items recorded", CENTER), "", "", "", "", "", "", ""])
    rows.append(["", p("Total", _style("tt", 8.5, True, BLUE_DARK)), "", p(qty_text, _style("tq", 8.5, True, BLUE_DARK, 2)), "", "", "", p(rs(sale.get("total")), _style("ta", 8.5, True, BLUE_DARK, 2))])
    widths = [8 * mm, 44 * mm, 20 * mm, 22 * mm, 16 * mm, 28 * mm, 14 * mm, 28 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    last = len(rows) - 1
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), .5, LINE), ("LINEBELOW", (0, 0), (-1, 0), .5, BLUE_DARK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BACKGROUND", (0, last), (-1, last), WASH), ("SPAN", (1, last), (2, last)),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    if not items:
        table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1))]))
    story += [table, Spacer(1, 3 * mm)]

    # totals
    total, received = Decimal(str(sale.get("total") or 0)), Decimal(str(sale.get("amount_received") or 0))
    summary = [["Total quantity", qty_text], ["Sub Total", rs(subtotal)], ["GST", rs(gst_total)], ["Total", rs(total)], ["Received", rs(received)],
               ["Balance", rs(max(Decimal(0), total - received))], ["Payment Mode", "Not recorded"], ["Invoice Amount In Words", in_words(total)]]
    srows = [[p(a), p(b, RIGHT if k < 7 else BODY)] for k, (a, b) in enumerate(summary)]
    srows[3] = [p("Total", _style("g1", 11, True, colors.white)), p(rs(total), _style("g2", 11, True, colors.white, 2))]
    st = Table(srows, colWidths=[WIDTH * .52, WIDTH * .48])
    st.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, LINE), ("BACKGROUND", (0, 3), (-1, 3), BLUE), ("BACKGROUND", (0, 7), (-1, 7), WASH), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
    sign = Table([[""], [Paragraph("Authorized Signatory", _style("sg", 8, color=MUTED, align=1))]], colWidths=[48 * mm], hAlign="RIGHT", rowHeights=[16 * mm, None])
    sign.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), .6, MUTED)]))
    story.append(KeepTogether([st, Spacer(1, 6 * mm), sign]))

    doc.build(story)
    return buf.getvalue()
