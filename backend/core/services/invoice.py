"""The invoice (Brand Book v3.5): one A4 page, drawn with ReportLab and the standard Helvetica fonts (no font files needed).
Same layout as the version that ran on the old service. Everything on it comes from the database, never from the phone."""
import io
import math
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.models import BillItem, Customer, Franchise, Lead, Profile, ScrapItem

IST = ZoneInfo("Asia/Kolkata")
REG, BOLD = "Helvetica", "Helvetica-Bold"


# ---------------------------------------------------------------------------------------------- formatting
def clean(s):
    s = "" if s is None else str(s)
    s = re.sub(r"[^\x20-\x7E -ÿ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _group_indian(whole):
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def money(n):
    n = Decimal(str(n)).quantize(Decimal("0.01"))
    whole, frac = format(abs(n), "f").split(".")
    return ("-" if n < 0 else "") + _group_indian(whole) + "." + frac


def kgs(n):
    return f"{Decimal(str(n)):.2f}"


def date_only(t):
    return t.astimezone(IST).strftime("%d %b %Y") if t else "-"


def time_only(t):
    if not t:
        return "-"
    d = t.astimezone(IST)
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def when(t):
    return f"{date_only(t)}, {time_only(t)}" if t else "-"


ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below100(n):
    return ONES[n] if n < 20 else TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")


def _below1000(n):
    h, r = divmod(n, 100)
    return " ".join(x for x in [ONES[h] + " Hundred" if h else "", _below100(r) if r else ""] if x)


def in_words(amount):
    amount = Decimal(str(amount))
    n = int(amount)
    paise = int(((amount - n) * 100).quantize(Decimal(1), rounding="ROUND_HALF_UP"))
    if n == 0 and paise == 0:
        return "Rupees Zero only"
    parts = []
    crore, n = divmod(n, 10000000)
    lakh, n = divmod(n, 100000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(_below1000(crore) + " Crore")
    if lakh:
        parts.append(_below100(lakh) + " Lakh")
    if thousand:
        parts.append(_below100(thousand) + " Thousand")
    if n:
        parts.append(_below1000(n))
    s = "Rupees " + (" ".join(parts) or "Zero")
    if paise:
        s += " and " + _below100(paise) + " Paise"
    return s + " only"


# ---------------------------------------------------------------------------------------------- the data
def bill_data(bill):
    lead = Lead.objects.get(pk=bill.lead_id)
    load = bill.load
    customer = Customer.objects.get(pk=lead.customer_id)
    driver = Profile.objects.get(pk=load.driver_id)
    franchise = Franchise.objects.filter(pk=driver.franchise_id).first() if driver.franchise_id else None
    rows = BillItem.objects.filter(bill_id=bill.pk).select_related("item")
    items = sorted(({"name": r.item.name, "qty": r.qty_kg, "rate": r.rate_per_kg, "amount": r.amount} for r in rows),
                   key=lambda x: x["name"].casefold())
    return {"bill": bill, "lead": lead, "load": load, "customer": customer, "driver": driver, "franchise": franchise, "items": items}


# ---------------------------------------------------------------------------------------------- brand shapes
# reduce (point down), reuse (circle), recycle (point up), drawn in a 110 x 100 box
P_DOWN = "M99.10 0.00L12.50 0.00A12.50 12.50 0 0 0 1.67 18.75L44.98 93.75A12.50 12.50 0 0 0 66.63 93.75L109.93 18.75A12.50 12.50 0 0 0 99.10 0.00Z"
P_UP = "M12.50 100.00L99.10 100.00A12.50 12.50 0 0 0 109.93 81.25L66.63 6.25A12.50 12.50 0 0 0 44.98 6.25L1.67 81.25A12.50 12.50 0 0 0 12.50 100.00Z"


def _rr(w, h, r):
    return (f"M{r},0 H{w - r} A{r},{r} 0 0 1 {w},{r} V{h - r} A{r},{r} 0 0 1 {w - r},{h} H{r} "
            f"A{r},{r} 0 0 1 0,{h - r} V{r} A{r},{r} 0 0 1 {r},0 Z")


NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _arc_segments(x1, y1, rx, ry, large, sweep, x2, y2):
    """SVG arc (no rotation) -> list of cubic bezier segments [(c1, c2, end), ...], in SVG coordinates."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [((x1, y1), (x2, y2), (x2, y2))]
    rx, ry = abs(rx), abs(ry)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    lam = dx * dx / (rx * rx) + dy * dy / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * dy / ry, -coef * ry * dx / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
    th1 = math.atan2((dy - cyp) / ry, (dx - cxp) / rx)
    th2 = math.atan2((-dy - cyp) / ry, (-dx - cxp) / rx)
    dth = th2 - th1
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    n = max(1, math.ceil(abs(dth) / (math.pi / 2) - 1e-9))
    delta = dth / n
    t = 4 / 3 * math.tan(delta / 4)
    out, a = [], th1
    for _ in range(n):
        b = a + delta
        p0 = (cx + rx * math.cos(a), cy + ry * math.sin(a))
        p3 = (cx + rx * math.cos(b), cy + ry * math.sin(b))
        c1 = (p0[0] - t * rx * math.sin(a), p0[1] + t * ry * math.cos(a))
        c2 = (p3[0] + t * rx * math.sin(b), p3[1] - t * ry * math.cos(b))
        out.append((c1, c2, p3))
        a = b
    return out


class Page:
    """A small drawing kit with the same call shapes the original used: coordinates start at the bottom-left of the page."""

    def __init__(self, canvas, W, H):
        self.c, self.W, self.H = canvas, W, H

    def _col(self, color, alpha=1.0):
        return color, alpha

    def rect(self, x, y, w, h, color, opacity=1):
        c = self.c
        c.saveState(); c.setFillColor(color); c.setFillAlpha(opacity)
        c.rect(x, y, w, h, stroke=0, fill=1)
        c.restoreState()

    def ellipse(self, x, y, xs, ys, color, opacity=1):
        c = self.c
        c.saveState(); c.setFillColor(color); c.setFillAlpha(opacity)
        c.ellipse(x - xs, y - ys, x + xs, y + ys, stroke=0, fill=1)
        c.restoreState()

    def circle(self, x, y, r, border, bw):
        c = self.c
        c.saveState(); c.setStrokeColor(border); c.setLineWidth(bw)
        c.circle(x, y, r, stroke=1, fill=0)
        c.restoreState()

    def svg_path(self, d, x, y, scale=1, color=None, border=None, bw=0.8, opacity=1):
        """Draw an SVG path whose origin sits at (x, y) with y growing downwards, like the original drawing call."""
        c = self.c
        tr = lambda px, py: (x + px * scale, y - py * scale)
        p = c.beginPath()
        toks = re.findall(r"[MLHVAZ]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
        i, cur, start, cmd = 0, (0.0, 0.0), (0.0, 0.0), None
        num = lambda: float(toks[i])
        while i < len(toks):
            if toks[i] in "MLHVAZ" and not NUM.fullmatch(toks[i]):
                cmd = toks[i]
                i += 1
                if cmd == "Z":
                    p.close(); cur = start
                    continue
            if cmd == "M":
                cur = (float(toks[i]), float(toks[i + 1])); i += 2
                p.moveTo(*tr(*cur)); start = cur; cmd = "L"
            elif cmd == "L":
                cur = (float(toks[i]), float(toks[i + 1])); i += 2
                p.lineTo(*tr(*cur))
            elif cmd == "H":
                cur = (float(toks[i]), cur[1]); i += 1
                p.lineTo(*tr(*cur))
            elif cmd == "V":
                cur = (cur[0], float(toks[i])); i += 1
                p.lineTo(*tr(*cur))
            elif cmd == "A":
                rx, ry, _rot, large, sweep, ex, ey = (float(toks[i + k]) for k in range(7)); i += 7
                for c1, c2, end in _arc_segments(cur[0], cur[1], rx, ry, int(large), int(sweep), ex, ey):
                    p.curveTo(*tr(*c1), *tr(*c2), *tr(*end))
                cur = (ex, ey)
            else:
                break
        c.saveState()
        if color is not None:
            c.setFillColor(color); c.setFillAlpha(opacity)
        if border is not None:
            c.setStrokeColor(border); c.setLineWidth(bw)
        c.drawPath(p, stroke=1 if border is not None else 0, fill=1 if color is not None else 0)
        c.restoreState()

    def box(self, x, y_top, w, h, r, color=None, border=None, bw=0.8, opacity=1):
        """A rounded box. (x, y_top) is its top-left corner."""
        self.svg_path(_rr(w, h, r), x, y_top, 1, color=color, border=border, bw=bw, opacity=opacity)

    def text(self, s, x, y, size=10, font=REG, color=None):
        c = self.c
        c.setFont(font, size); c.setFillColor(color)
        c.drawString(x, y, clean(s))

    def right(self, s, xr, y, size=10, font=REG, color=None):
        s = clean(s)
        self.text(s, xr - stringWidth(s, font, size), y, size, font, color)

    def wrap(self, s, width, size, font=REG):
        words, lines, cur = clean(s).split(" "), [], ""
        for w in words:
            t = f"{cur} {w}" if cur else w
            if stringWidth(t, font, size) <= width:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or ["-"]


def _hex(h):
    return Color(((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255)


def build_pdf(d):
    """Make the one-page bill. Returns the PDF as bytes."""
    W, H, M = 595.28, 841.89, 40
    R = W - M
    CW = R - M
    buf = io.BytesIO()
    cv = Canvas(buf, pagesize=(W, H), pageCompression=1)
    bill = d["bill"]
    cv.setTitle(f"Scrappy bill {bill.bill_no}")
    cv.setAuthor("Scrappy Innovations Pvt. Ltd.")
    pg = Page(cv, W, H)

    OX, OX7, OX9, OX100, OX200 = _hex(0x8b1e24), _hex(0x5e1318), _hex(0x300a0c), _hex(0xf5dede), _hex(0xe9b9bb)
    INK, STONE, FAINT, LINE, PAPER, CARD = _hex(0x2a2426), _hex(0x5a5452), _hex(0x6b6563), _hex(0xe4e1dc), _hex(0xfaf8f7), _hex(0xfcfbfa)
    WHITE = Color(1, 1, 1)
    GREEN, GREEN_D, GREEN_T = _hex(0x2e7d4f), _hex(0x17462b), _hex(0xeaf5ee)
    AMBER, AMBER_D, AMBER_T = _hex(0x8f5b0e), _hex(0x4d3007), _hex(0xfbf1dc)
    text, right, wrap, box, shape = pg.text, pg.right, pg.wrap, pg.box, pg.svg_path

    logo = None
    try:
        if settings.BILL_LOGO_FILE.exists():
            logo = ImageReader(str(settings.BILL_LOGO_FILE))
    except Exception:
        logo = None             # a missing picture never blocks a bill: a text badge is drawn instead

    paid = bill.status == "paid"
    items = d["items"]
    total_kg = sum((i["qty"] for i in items), Decimal(0))
    total = sum((i["amount"] for i in items), Decimal(0))
    fr = d["franchise"]
    fr_name, fr_code = clean(fr.name if fr else ""), clean(fr.code if fr else "")
    method = "UPI" if bill.payment_method == "upi" else "Cash"

    # ===== header band =====
    HH = 158
    pg.rect(0, H - HH, W, HH, OX)
    pg.ellipse(90, H - 10, 190, 100, WHITE, 0.06)
    pg.ellipse(W - 30, H - HH + 34, 210, 30, OX9, 0.28)
    shape(P_UP, W - 150, H - 14, 1.1, color=WHITE, opacity=0.07)
    shape(P_DOWN, W - 330, H - HH + 64, 0.5, color=WHITE, opacity=0.07)
    pg.ellipse(W - 250, H - 38, 20, 20, WHITE, 0.07)
    bw_ = 138
    if logo:
        iw, ih = logo.getSize()
        bh = bw_ * ih / iw
        box(M - 6, H - 26, bw_ + 12, bh + 16, 6, color=WHITE)
        cv.drawImage(logo, M, H - 34 - bh, width=bw_, height=bh, mask="auto")
    else:
        bh = 80
        pg.ellipse(M + bw_ / 2, H - 34 - bh / 2, bw_ / 2, bh / 2, WHITE)
        w = stringWidth("SCRAPPY", BOLD, 24)
        text("SCRAPPY", M + (bw_ - w) / 2, H - 34 - bh / 2 - 8, 24, BOLD, OX)
    eyebrow = "SCRAP PICKUP"
    ew = stringWidth(eyebrow, BOLD, 8.5)
    right(eyebrow, R, H - 46, 8.5, BOLD, OX100)
    shape(P_DOWN, R - ew - 44, H - 40, 0.075, color=WHITE)
    pg.ellipse(R - ew - 29, H - 43.5, 3.7, 3.7, WHITE)
    shape(P_UP, R - ew - 22, H - 39.5, 0.075, color=WHITE)
    right("Pickup bill", R, H - 78, 28, BOLD, WHITE)
    right(f"Bill no  {bill.bill_no}", R, H - 98, 11.5, BOLD, WHITE)
    right(f"Lead {d['lead'].code}  ·  Load {d['load'].code}", R, H - 113, 8.5, REG, OX100)

    # ===== info card straddling the header =====
    mh, m_top = 50, H - HH + 28
    pg.ellipse(W / 2, m_top - mh - 1, CW / 2 - 6, 3, OX9, 0.05)
    box(M, m_top, CW, mh, 10, color=WHITE, border=LINE)
    when_bill = bill.sent_at or bill.created_at
    cols = [("BILL DATE", date_only(when_bill), time_only(when_bill)),
            ("FRANCHISE", fr_name or "Scrappy", f"Code {fr_code}" if fr_code else ""),
            ("TOTAL WEIGHT", f"{kgs(total_kg)} kg", f"{len(items)} item{'' if len(items) == 1 else 's'}")]
    for i, col in enumerate(cols):
        cx = M + (CW / 3) * i + 16
        if i:
            pg.rect(M + (CW / 3) * i, m_top - mh + 10, 0.8, mh - 20, LINE)
        text(col[0], cx, m_top - 15, 6.5, BOLD, FAINT)
        text(col[1], cx, m_top - 29, 11.5, BOLD, INK)
        if col[2]:
            text(col[2], cx, m_top - 41, 8.5, REG, STONE)

    # ===== customer and collector =====
    y = m_top - mh - 38
    col_w = (CW - 16) / 2
    x2, pad = M + col_w + 16, 14
    cust = d["customer"]
    cust_lines = wrap(", ".join(x for x in [cust.address, cust.area] if x), col_w - pad * 2, 9)
    card_h = 34 + 14 + (12 if cust.phone else 0) + len(cust_lines) * 11.5 + 12
    card_top = y
    box(M, card_top, col_w, card_h, 10, color=CARD, border=LINE)
    box(x2, card_top, col_w, card_h, 10, color=CARD, border=LINE)
    text("PAID TO", M + pad, card_top - 16, 7, BOLD, OX)
    text("COLLECTED BY", x2 + pad, card_top - 16, 7, BOLD, OX)
    yl = yr = card_top - 33
    text(cust.name or "-", M + pad, yl, 12, BOLD, INK); yl -= 14
    if cust.phone:
        text(str(cust.phone), M + pad, yl, 9, REG, STONE); yl -= 12
    for ln in cust_lines:
        text(ln, M + pad, yl, 9, REG, STONE); yl -= 11.5
    drv = d["driver"]
    text(drv.full_name or "-", x2 + pad, yr, 12, BOLD, INK); yr -= 14
    veh = "  ·  ".join(x for x in [("Vehicle " + drv.vehicle_no) if drv.vehicle_no else "", drv.territory or ""] if x)
    if veh:
        text(veh, x2 + pad, yr, 9, REG, STONE); yr -= 12
    text(f"Scrappy {fr_name or 'collection partner'}{' (' + fr_code + ')' if fr_code else ''}", x2 + pad, yr, 9, REG, STONE)

    # status stamp, tilted, sitting on the top edge of the collector card
    l1 = "PAID" if paid else "NOT PAID YET"
    l2 = f"{date_only(bill.paid_at)}  ·  {method}" if paid else "Paid after you agree"
    s1, s2 = 15, 7.5
    sw = max(stringWidth(l1, BOLD, s1), stringWidth(l2, REG, s2)) + 28
    sh = 36
    col = GREEN if paid else AMBER
    a = 8 * math.pi / 180
    cos, sin = math.cos(a), math.sin(a)
    cx, cy = R - sw / 2 - 12, card_top + 12
    at = lambda dx, dy: (cx + dx * cos - dy * sin, cy + dx * sin + dy * cos)
    pts = [at(-sw / 2, sh / 2), at(sw / 2, sh / 2), at(sw / 2, -sh / 2), at(-sw / 2, -sh / 2)]
    poly = "M" + " L".join(f"{px:.2f},{H - py:.2f}" for px, py in pts) + " Z"
    pg.svg_path(poly, 0, H, 1, color=WHITE, border=col, bw=2, opacity=0.96)
    for label, size, font, dx, dy in ((l1, s1, BOLD, -stringWidth(l1, BOLD, s1) / 2, -1), (l2, s2, REG, -stringWidth(l2, REG, s2) / 2, -12.5)):
        px, py = at(dx, dy)
        cv.saveState(); cv.translate(px, py); cv.rotate(8)
        cv.setFont(font, size); cv.setFillColor(col); cv.drawString(0, 0, clean(label))
        cv.restoreState()
    y = card_top - card_h - 22

    # ===== items table =====
    n = len(items)
    row_h = 24 if n <= 8 else 20 if n <= 12 else 16
    c_item, c_qty, c_rate, c_amt = M + 14, M + 290, M + 392, R - 14
    box(M, y + 8, CW, 24, 7, color=INK)
    text("ITEM", c_item, y - 1, 7.5, BOLD, WHITE)
    right("WEIGHT (KG)", c_qty, y - 1, 7.5, BOLD, WHITE)
    right("RATE (RS / KG)", c_rate, y - 1, 7.5, BOLD, WHITE)
    right("AMOUNT (RS)", c_amt, y - 1, 7.5, BOLD, WHITE)
    y -= 32
    for i, it in enumerate(items):
        if i % 2 == 1:
            pg.rect(M, y - 8, CW, row_h, PAPER)
        pg.rect(M, y - 8, CW, 0.6, LINE)
        text(it["name"], c_item, y, 10, BOLD, INK)
        right(kgs(it["qty"]), c_qty, y, 10, REG, INK)
        right(money(it["rate"]), c_rate, y, 10, REG, STONE)
        right(money(it["amount"]), c_amt, y, 10, BOLD, INK)
        y -= row_h
    pg.rect(M, y + row_h - 8 - 0.6, CW, 1.4, INK)
    text("Total", c_item, y - 3, 10.5, BOLD, INK)
    right(kgs(total_kg) + " kg", c_qty, y - 3, 10.5, BOLD, INK)
    right(money(total), c_amt, y - 3, 10.5, BOLD, INK)
    y -= 34

    # ===== payment box + total box =====
    rows = [("Status", "Paid" if paid else "Waiting for payment", GREEN if paid else AMBER), ("Method", method if paid else "-", INK)]
    if paid and bill.payment_method == "upi" and bill.upi_ref:
        rows.append(("UPI reference", str(bill.upi_ref), INK))
    if paid:
        rows.append(("Paid on", when(bill.paid_at), INK))
    if bill.confirmed_at:
        rows.append(("Agreed on", when(bill.confirmed_at), INK))
    pay_w = 204
    tot_w = CW - pay_w - 14
    sum_h = max(88, 30 + len(rows) * 14 + 8)
    sum_top = y + 8
    box(M, sum_top, pay_w, sum_h, 10, color=WHITE, border=LINE)
    text("PAYMENT", M + 14, sum_top - 17, 7, BOLD, FAINT)
    for i, r in enumerate(rows):
        ry = sum_top - 33 - i * 14
        text(r[0], M + 14, ry, 8.5, REG, STONE)
        right(r[1], M + pay_w - 14, ry, 8.5, BOLD, r[2])
    tx = M + pay_w + 14
    box(tx, sum_top, tot_w, sum_h, 10, color=OX)
    pg.ellipse(tx + tot_w - 14, sum_top - 4, 46, 46, WHITE, 0.08)
    box(tx, sum_top, tot_w, sum_h, 10, border=OX7, bw=0.6)
    text("AMOUNT PAID TO YOU" if paid else "AMOUNT YOU WILL RECEIVE", tx + 16, sum_top - 18, 7.5, BOLD, OX100)
    text("Rs. " + money(total), tx + 16, sum_top - 46, 25, BOLD, WHITE)
    for i, ln in enumerate(wrap(in_words(total), tot_w - 32, 8)[:2]):
        text(ln, tx + 16, sum_top - 64 - i * 10.5, 8, REG, OX100)
    y = sum_top - sum_h - 22

    # ===== note =====
    note = ("Thank you for choosing Scrappy. This bill is now closed and the payment is recorded." if paid else
            "Please check the weights and rates. Tell the collector if anything looks wrong. We pay as soon as you agree to this bill.")
    nl = wrap(note, CW - 52, 9)
    nh = 18 + len(nl) * 12
    box(M, y + 8, CW, nh, 10, color=GREEN_T if paid else AMBER_T)
    pg.circle(M + 24, y + 8 - nh / 2, 7.5, GREEN_D if paid else AMBER_D, 1.4)
    if paid:
        pg.svg_path("M0,0 L2.6,2.8 L7,-3", M + 20.7, y + 8 - nh / 2 + 0.3, 1, border=GREEN_D, bw=1.4)
    else:
        pg.rect(M + 23.4, y + 8 - nh / 2 - 0.5, 1.3, 5, AMBER_D)
        pg.rect(M + 23.4, y + 8 - nh / 2 - 0.5, 4, 1.3, AMBER_D)
    for i, ln in enumerate(nl):
        text(ln, M + 42, y + 8 - 17 - i * 12, 9, REG, GREEN_D if paid else AMBER_D)
    y -= nh + 14
    if y > 84:
        for ln in wrap("Rates are fixed by Scrappy HQ for the day. Weights were recorded at your premises in your presence. "
                       "This is a computer-generated bill and needs no signature.", CW, 7.5):
            text(ln, M, y, 7.5, REG, FAINT)
            y -= 10

    # ===== footer =====
    pg.rect(0, 5, W, 58, INK)
    pg.rect(0, 0, W, 5, OX)
    text("Waste management, ", M, 40, 12.5, BOLD, WHITE)
    text("made simple.", M + stringWidth("Waste management, ", BOLD, 12.5), 40, 12.5, BOLD, OX200)
    now = datetime.now(IST)
    text(f"Scrappy Innovations Pvt. Ltd.  ·  Kerala  ·  {bill.bill_no}  ·  Generated {when(now)}", M, 24, 7.5, REG, _hex(0xc9c5bf))
    signatory_label = "Authorized Signatory"
    signatory_xr = R - 70
    cv.saveState()
    cv.setStrokeColor(_hex(0xc9c5bf))
    cv.setLineWidth(0.7)
    cv.line(signatory_xr - 116, 20, signatory_xr, 20)
    cv.restoreState()
    right(signatory_label, signatory_xr, 10, 7.5, REG, _hex(0xc9c5bf))
    shape(P_DOWN, R - 62, 46, 0.17, color=OX)
    pg.ellipse(R - 31, 36.5, 8.6, 8.6, OX)
    shape(P_UP, R - 20, 46, 0.17, color=OX)

    cv.showPage()
    cv.save()
    return buf.getvalue()
