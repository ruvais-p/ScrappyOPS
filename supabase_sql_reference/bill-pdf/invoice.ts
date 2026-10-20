// Scrappy · invoice design (Brand Book v3.5). Draws the one-page A4 pickup bill with pdf-lib.
// Used by the bill-pdf edge function. Standard Helvetica fonts only (no font downloads, so it never fails on a font).
import { PDFDocument, StandardFonts, rgb, degrees } from "npm:pdf-lib@1.17.1";

/* ---------- formatting helpers ---------- */
export const clean = (s: unknown) => String(s ?? "").replace(/[^\x20-\x7E -ÿ]/g, "").replace(/\s+/g, " ").trim();
const money = (n: number) => Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const kgs = (n: number) => Number(n).toFixed(2);
const IST = "Asia/Kolkata";
const dateOnly = (t: string | null) => t ? new Date(t).toLocaleDateString("en-IN", { timeZone: IST, day: "2-digit", month: "short", year: "numeric" }) : "-";
const timeOnly = (t: string | null) => t ? new Date(t).toLocaleTimeString("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit", hour12: true }).replace(/\b(am|pm)\b/, (m) => m.toUpperCase()) : "-";
const when = (t: string | null) => t ? `${dateOnly(t)}, ${timeOnly(t)}` : "-";

const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
  "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
function below100(n: number) { return n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? " " + ONES[n % 10] : ""); }
function below1000(n: number) {
  const h = Math.floor(n / 100), r = n % 100;
  return [h ? ONES[h] + " Hundred" : "", r ? below100(r) : ""].filter(Boolean).join(" ");
}
export function inWords(amount: number) {
  let n = Math.floor(amount);
  const paise = Math.round((amount - n) * 100);
  if (n === 0 && paise === 0) return "Rupees Zero only";
  const parts: string[] = [];
  const crore = Math.floor(n / 10000000); n %= 10000000;
  const lakh = Math.floor(n / 100000); n %= 100000;
  const thousand = Math.floor(n / 1000); n %= 1000;
  if (crore) parts.push(below1000(crore) + " Crore");
  if (lakh) parts.push(below100(lakh) + " Lakh");
  if (thousand) parts.push(below100(thousand) + " Thousand");
  if (n) parts.push(below1000(n));
  let s = "Rupees " + (parts.join(" ") || "Zero");
  if (paise) s += " and " + below100(paise) + " Paise";
  return s + " only";
}

export type BillData = {
  bill: Record<string, any>; lead: Record<string, any>; load: Record<string, any>;
  customer: Record<string, any>; driver: Record<string, any>; franchise: Record<string, any> | null;
  items: { name: string; qty: number; rate: number; amount: number }[];
};

/* brand paths: reduce (point down), reuse (circle), recycle (point up), drawn in a 110 x 100 box */
const P_DOWN = "M99.10 0.00L12.50 0.00A12.50 12.50 0 0 0 1.67 18.75L44.98 93.75A12.50 12.50 0 0 0 66.63 93.75L109.93 18.75A12.50 12.50 0 0 0 99.10 0.00Z";
const P_UP = "M12.50 100.00L99.10 100.00A12.50 12.50 0 0 0 109.93 81.25L66.63 6.25A12.50 12.50 0 0 0 44.98 6.25L1.67 81.25A12.50 12.50 0 0 0 12.50 100.00Z";
const rr = (w: number, h: number, r: number) =>
  `M${r},0 H${w - r} A${r},${r} 0 0 1 ${w},${r} V${h - r} A${r},${r} 0 0 1 ${w - r},${h} H${r} A${r},${r} 0 0 1 0,${h - r} V${r} A${r},${r} 0 0 1 ${r},0 Z`;
/* The badge image is a static file on the Scrappy site (bill-badge.png). It is fetched once, checked against its length and
   checksum, and if anything is off the bill is drawn with a text badge instead, so a bill is never blocked by the image. */
const BADGE_URL = "https://scrappy-manager.scrappyinnovationsltd.workers.dev/bill-badge.png";
const BADGE_LEN = 4963, BADGE_HASH = 2734590102;
let badgeCache: Uint8Array | null = null;
async function loadBadge(): Promise<Uint8Array | null> {
  if (badgeCache) return badgeCache;
  try {
    const r = await fetch(BADGE_URL, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return null;
    const bytes = new Uint8Array(await r.arrayBuffer());
    if (bytes.length !== BADGE_LEN) return null;
    let x = 0x811c9dc5; for (let i = 0; i < bytes.length; i++) { x ^= bytes[i]; x = Math.imul(x, 0x01000193) >>> 0; }
    if (x !== BADGE_HASH) return null;
    return (badgeCache = bytes);
  } catch (_) { return null; }
}
const hex = (h: number) => rgb(((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255);

export async function buildPdf(d: BillData): Promise<Uint8Array> {
  const pdf = await PDFDocument.create();
  pdf.setTitle(`Scrappy bill ${d.bill.bill_no}`);
  pdf.setAuthor("Scrappy Innovations Pvt. Ltd.");
  const W = 595.28, H = 841.89, M = 40, R = W - M, CW = R - M;
  const page = pdf.addPage([W, H]);
  const reg = await pdf.embedFont(StandardFonts.Helvetica);
  const bold = await pdf.embedFont(StandardFonts.HelveticaBold);
  const badgeBytes = await loadBadge();
  const badge = badgeBytes ? await pdf.embedPng(badgeBytes) : null;

  const OX = hex(0x8b1e24), OX7 = hex(0x5e1318), OX9 = hex(0x300a0c), OX100 = hex(0xf5dede), OX200 = hex(0xe9b9bb), OXT = hex(0xfbf1f1);
  const INK = hex(0x2a2426), STONE = hex(0x5a5452), FAINT = hex(0x6b6563), LINE = hex(0xe4e1dc), PAPER = hex(0xfaf8f7), CARD = hex(0xfcfbfa), WHITE = rgb(1, 1, 1);
  const GREEN = hex(0x2e7d4f), GREEN_D = hex(0x17462b), GREEN_T = hex(0xeaf5ee), AMBER = hex(0x8f5b0e), AMBER_D = hex(0x4d3007), AMBER_T = hex(0xfbf1dc);

  const text = (s: string, x: number, y: number, size = 10, font = reg, color = INK) => page.drawText(clean(s), { x, y, size, font, color });
  const right = (s: string, xr: number, y: number, size = 10, font = reg, color = INK) =>
    page.drawText(clean(s), { x: xr - font.widthOfTextAtSize(clean(s), size), y, size, font, color });
  const wrap = (s: string, width: number, size: number, font = reg) => {
    const words = clean(s).split(" "); const lines: string[] = []; let cur = "";
    for (const w of words) {
      const t = cur ? cur + " " + w : w;
      if (font.widthOfTextAtSize(t, size) <= width) cur = t; else { if (cur) lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    return lines.length ? lines : ["-"];
  };
  /* rounded box: (x, yTop) is its top-left corner */
  const box = (x: number, yTop: number, w: number, h: number, r: number, o: { color?: any; border?: any; bw?: number; opacity?: number } = {}) =>
    page.drawSvgPath(rr(w, h, r), { x, y: yTop, color: o.color, borderColor: o.border, borderWidth: o.border ? (o.bw ?? 0.8) : undefined, opacity: o.opacity });
  const shape = (p: string, x: number, yTop: number, scale: number, color: any, opacity = 1) => page.drawSvgPath(p, { x, y: yTop, scale, color, opacity });

  const paid = d.bill.status === "paid";
  const totalKg = d.items.reduce((a, b) => a + b.qty, 0);
  const total = d.items.reduce((a, b) => a + b.amount, 0);
  const frName = clean(d.franchise?.name || ""), frCode = clean(d.franchise?.code || "");
  const method = d.bill.payment_method === "upi" ? "UPI" : "Cash";

  /* ===== header band ===== */
  const HH = 158;
  page.drawRectangle({ x: 0, y: H - HH, width: W, height: HH, color: OX });
  page.drawEllipse({ x: 90, y: H - 10, xScale: 190, yScale: 100, color: WHITE, opacity: 0.06 });
  page.drawEllipse({ x: W - 30, y: H - HH + 34, xScale: 210, yScale: 30, color: OX9, opacity: 0.28 });
  shape(P_UP, W - 150, H - 14, 1.1, WHITE, 0.07);
  shape(P_DOWN, W - 330, H - HH + 64, 0.5, WHITE, 0.07);
  page.drawEllipse({ x: W - 250, y: H - 38, xScale: 20, yScale: 20, color: WHITE, opacity: 0.07 });
  const bw = 138, bh = badge ? bw * badge.height / badge.width : 80;
  if (badge) page.drawImage(badge, { x: M, y: H - 34 - bh, width: bw, height: bh });
  else { page.drawEllipse({ x: M + bw / 2, y: H - 34 - bh / 2, xScale: bw / 2, yScale: bh / 2, color: WHITE }); const w = bold.widthOfTextAtSize("SCRAPPY", 24); page.drawText("SCRAPPY", { x: M + (bw - w) / 2, y: H - 34 - bh / 2 - 8, size: 24, font: bold, color: OX }); }
  /* three-shapes mark + title block */
  const eyebrow = "SCRAP PICKUP", ew = bold.widthOfTextAtSize(eyebrow, 8.5);
  right(eyebrow, R, H - 46, 8.5, bold, OX100);
  shape(P_DOWN, R - ew - 44, H - 40, 0.075, WHITE); page.drawEllipse({ x: R - ew - 29, y: H - 43.5, xScale: 3.7, yScale: 3.7, color: WHITE }); shape(P_UP, R - ew - 22, H - 39.5, 0.075, WHITE);
  right("Pickup bill", R, H - 78, 28, bold, WHITE);
  right(`Bill no  ${d.bill.bill_no}`, R, H - 98, 11.5, bold, WHITE);
  right(`Lead ${d.lead.code}  ·  Load ${d.load.code}`, R, H - 113, 8.5, reg, OX100);

  /* ===== info card straddling the header ===== */
  const mh = 50, mTop = H - HH + 28;
  page.drawEllipse({ x: W / 2, y: mTop - mh - 1, xScale: CW / 2 - 6, yScale: 3, color: OX9, opacity: 0.05 });
  box(M, mTop, CW, mh, 10, { color: WHITE, border: LINE });
  const cols = [
    ["BILL DATE", dateOnly(d.bill.sent_at ?? d.bill.created_at), timeOnly(d.bill.sent_at ?? d.bill.created_at)],
    ["FRANCHISE", frName || "Scrappy", frCode ? `Code ${frCode}` : ""],
    ["TOTAL WEIGHT", `${kgs(totalKg)} kg`, `${d.items.length} item${d.items.length === 1 ? "" : "s"}`],
  ];
  cols.forEach((c, i) => {
    const cx = M + (CW / 3) * i + 16;
    if (i) page.drawRectangle({ x: M + (CW / 3) * i, y: mTop - mh + 10, width: 0.8, height: mh - 20, color: LINE });
    text(c[0], cx, mTop - 15, 6.5, bold, FAINT); text(c[1], cx, mTop - 29, 11.5, bold); if (c[2]) text(c[2], cx, mTop - 41, 8.5, reg, STONE);
  });

  /* ===== customer and collector ===== */
  let y = mTop - mh - 38;
  const colW = (CW - 16) / 2, x2 = M + colW + 16, pad = 14;
  const custLines = wrap([d.customer.address, d.customer.area].filter(Boolean).join(", "), colW - pad * 2, 9);
  const cardH = 34 + 14 + (d.customer.phone ? 12 : 0) + custLines.length * 11.5 + 12;
  const cardTop = y;
  box(M, cardTop, colW, cardH, 10, { color: CARD, border: LINE });
  box(x2, cardTop, colW, cardH, 10, { color: CARD, border: LINE });
  text("PAID TO", M + pad, cardTop - 16, 7, bold, OX);
  text("COLLECTED BY", x2 + pad, cardTop - 16, 7, bold, OX);
  let yl = cardTop - 33, yr = cardTop - 33;
  text(d.customer.name || "-", M + pad, yl, 12, bold); yl -= 14;
  if (d.customer.phone) { text(String(d.customer.phone), M + pad, yl, 9, reg, STONE); yl -= 12; }
  for (const l of custLines) { text(l, M + pad, yl, 9, reg, STONE); yl -= 11.5; }
  text(d.driver.full_name || "-", x2 + pad, yr, 12, bold); yr -= 14;
  const veh = [d.driver.vehicle_no ? "Vehicle " + d.driver.vehicle_no : "", d.driver.territory || ""].filter(Boolean).join("  ·  ");
  if (veh) { text(veh, x2 + pad, yr, 9, reg, STONE); yr -= 12; }
  text(`Scrappy ${frName || "collection partner"}${frCode ? " (" + frCode + ")" : ""}`, x2 + pad, yr, 9, reg, STONE);

  /* status stamp, tilted, sitting on the top edge of the collector card */
  {
    const l1 = paid ? "PAID" : "NOT PAID YET", l2 = paid ? `${dateOnly(d.bill.paid_at)}  ·  ${method}` : "Paid after you agree";
    const s1 = 15, s2 = 7.5, sw = Math.max(bold.widthOfTextAtSize(l1, s1), reg.widthOfTextAtSize(l2, s2)) + 28, sh = 36;
    const col = paid ? GREEN : AMBER, a = 8 * Math.PI / 180, cos = Math.cos(a), sin = Math.sin(a);
    const cx = R - sw / 2 - 12, cy = cardTop + 12;
    const at = (dx: number, dy: number) => ({ x: cx + dx * cos - dy * sin, y: cy + dx * sin + dy * cos });
    const pts = [at(-sw / 2, sh / 2), at(sw / 2, sh / 2), at(sw / 2, -sh / 2), at(-sw / 2, -sh / 2)];
    page.drawSvgPath('M' + pts.map((p) => p.x.toFixed(2) + ',' + (H - p.y).toFixed(2)).join(' L') + ' Z', { x: 0, y: H, color: WHITE, borderColor: col, borderWidth: 2, opacity: 0.96, borderOpacity: 1 });
    const p1 = at(-bold.widthOfTextAtSize(l1, s1) / 2, -1), p2 = at(-reg.widthOfTextAtSize(l2, s2) / 2, -12.5);
    page.drawText(l1, { x: p1.x, y: p1.y, size: s1, font: bold, color: col, rotate: degrees(8) });
    page.drawText(l2, { x: p2.x, y: p2.y, size: s2, font: reg, color: col, rotate: degrees(8) });
  }
  y = cardTop - cardH - 22;

  /* ===== items table ===== */
  const n = d.items.length, rowH = n <= 8 ? 24 : n <= 12 ? 20 : 16;
  const cItem = M + 14, cQty = M + 290, cRate = M + 392, cAmt = R - 14;
  box(M, y + 8, CW, 24, 7, { color: INK });
  text("ITEM", cItem, y - 1, 7.5, bold, WHITE);
  right("WEIGHT (KG)", cQty, y - 1, 7.5, bold, WHITE);
  right("RATE (RS / KG)", cRate, y - 1, 7.5, bold, WHITE);
  right("AMOUNT (RS)", cAmt, y - 1, 7.5, bold, WHITE);
  y -= 32;
  d.items.forEach((it, i) => {
    if (i % 2 === 1) page.drawRectangle({ x: M, y: y - 8, width: CW, height: rowH, color: PAPER });
    page.drawRectangle({ x: M, y: y - 8, width: CW, height: 0.6, color: LINE });
    text(it.name, cItem, y, 10, bold);
    right(kgs(it.qty), cQty, y, 10);
    right(money(it.rate), cRate, y, 10, reg, STONE);
    right(money(it.amount), cAmt, y, 10, bold);
    y -= rowH;
  });
  page.drawRectangle({ x: M, y: y + rowH - 8 - 0.6, width: CW, height: 1.4, color: INK });
  text("Total", cItem, y - 3, 10.5, bold);
  right(kgs(totalKg) + " kg", cQty, y - 3, 10.5, bold);
  right(money(total), cAmt, y - 3, 10.5, bold);
  y -= 34;

  /* ===== payment box + total box ===== */
  const rows: [string, string, any][] = [["Status", paid ? "Paid" : "Waiting for payment", paid ? GREEN : AMBER], ["Method", paid ? method : "-", INK]];
  if (paid && d.bill.payment_method === "upi" && d.bill.upi_ref) rows.push(["UPI reference", String(d.bill.upi_ref), INK]);
  if (paid) rows.push(["Paid on", when(d.bill.paid_at), INK]);
  if (d.bill.confirmed_at) rows.push(["Agreed on", when(d.bill.confirmed_at), INK]);
  const payW = 204, totW = CW - payW - 14, sumH = Math.max(88, 30 + rows.length * 14 + 8), sumTop = y + 8;
  box(M, sumTop, payW, sumH, 10, { color: WHITE, border: LINE });
  text("PAYMENT", M + 14, sumTop - 17, 7, bold, FAINT);
  rows.forEach((r, i) => { const ry = sumTop - 33 - i * 14; text(r[0], M + 14, ry, 8.5, reg, STONE); right(r[1], M + payW - 14, ry, 8.5, bold, r[2]); });
  const tx = M + payW + 14;
  box(tx, sumTop, totW, sumH, 10, { color: OX });
  page.drawEllipse({ x: tx + totW - 14, y: sumTop - 4, xScale: 46, yScale: 46, color: WHITE, opacity: 0.08 });
  box(tx, sumTop, totW, sumH, 10, { border: OX7, bw: 0.6 });
  text(paid ? "AMOUNT PAID TO YOU" : "AMOUNT YOU WILL RECEIVE", tx + 16, sumTop - 18, 7.5, bold, OX100);
  text("Rs. " + money(total), tx + 16, sumTop - 46, 25, bold, WHITE);
  const wl = wrap(inWords(total), totW - 32, 8);
  wl.slice(0, 2).forEach((l, i) => text(l, tx + 16, sumTop - 64 - i * 10.5, 8, reg, OX100));
  y = sumTop - sumH - 22;

  /* ===== note ===== */
  const note = paid
    ? "Thank you for choosing Scrappy. This bill is now closed and the payment is recorded."
    : "Please check the weights and rates. Tell the collector if anything looks wrong. We pay as soon as you agree to this bill.";
  const nl = wrap(note, CW - 52, 9);
  const nh = 18 + nl.length * 12;
  box(M, y + 8, CW, nh, 10, { color: paid ? GREEN_T : AMBER_T });
  page.drawCircle({ x: M + 24, y: y + 8 - nh / 2, size: 7.5, borderColor: paid ? GREEN_D : AMBER_D, borderWidth: 1.4 });
  if (paid) page.drawSvgPath("M0,0 L2.6,2.8 L7,-3", { x: M + 20.7, y: y + 8 - nh / 2 + 0.3, borderColor: GREEN_D, borderWidth: 1.4 });
  else { page.drawRectangle({ x: M + 23.4, y: y + 8 - nh / 2 - 0.5, width: 1.3, height: 5, color: AMBER_D }); page.drawRectangle({ x: M + 23.4, y: y + 8 - nh / 2 - 0.5, width: 4, height: 1.3, color: AMBER_D }); }
  nl.forEach((l, i) => text(l, M + 42, y + 8 - 17 - i * 12, 9, reg, paid ? GREEN_D : AMBER_D));
  y -= nh + 14;
  if (y > 84) for (const l of wrap("Rates are fixed by Scrappy HQ for the day. Weights were recorded at your premises in your presence. This is a computer-generated bill and needs no signature.", CW, 7.5)) { text(l, M, y, 7.5, reg, FAINT); y -= 10; }

  /* ===== footer ===== */
  page.drawRectangle({ x: 0, y: 5, width: W, height: 58, color: INK });
  page.drawRectangle({ x: 0, y: 0, width: W, height: 5, color: OX });
  text("Waste management, ", M, 40, 12.5, bold, WHITE);
  text("made simple.", M + bold.widthOfTextAtSize("Waste management, ", 12.5), 40, 12.5, bold, OX200);
  text(`Scrappy Innovations Pvt. Ltd.  ·  Kerala  ·  ${d.bill.bill_no}  ·  Generated ${when(new Date().toISOString())}`, M, 24, 7.5, reg, hex(0xc9c5bf));
  shape(P_DOWN, R - 62, 46, 0.17, OX); page.drawEllipse({ x: R - 31, y: 36.5, xScale: 8.6, yScale: 8.6, color: OX }); shape(P_UP, R - 20, 46, 0.17, OX);
  void OXT;

  return await pdf.save();
}
