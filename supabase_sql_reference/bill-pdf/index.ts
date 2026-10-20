// Scrappy · bill-pdf
// Builds the PDF bill from the database (never from the phone), stores it in the private
// "bills" bucket and returns a fixed link the driver sends on WhatsApp.
// Opening that link always gives the newest PDF, so after payment it shows PAID.
// The invoice design (Brand Book v3.5) lives in invoice.ts.
import { createClient } from "npm:@supabase/supabase-js@2";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@5.9.6";
import { buildPdf } from "./invoice.ts";

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const JWKS = createRemoteJWKSet(new URL(`${SB_URL}/auth/v1/.well-known/jwks.json`));
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-test-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

/* ---------- customer link: always sends the newest PDF ---------- */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const shareLink = (token: string) => `${SB_URL}/functions/v1/bill-pdf?t=${token}`;
async function openLatest(req: Request): Promise<Response> {
  const t = new URL(req.url).searchParams.get("t") ?? "";
  const plain = (msg: string, status: number) =>
    new Response(msg, { status, headers: { ...cors, "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
  if (!UUID.test(t)) return plain("This bill link is not valid.", 404);
  const admin = createClient(SB_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data: bill } = await admin.from("bills").select("bill_no, pdf_path").eq("share_token", t).maybeSingle();
  if (!bill?.pdf_path) return plain("This bill is not ready yet. Please try again in a minute.", 404);
  const { data: signed, error } = await admin.storage.from("bills").createSignedUrl(bill.pdf_path, 300);
  if (error || !signed) return plain("Could not open the bill. Please try again.", 500);
  // a fresh address every time, so phones never show an old saved copy
  const dest = signed.signedUrl + (signed.signedUrl.includes("?") ? "&" : "?") + "v=" + Date.now();
  return new Response(null, { status: 302, headers: { ...cors, Location: dest, "Cache-Control": "no-store, max-age=0" } });
}

/* ---------- request ---------- */
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method === "GET") return openLatest(req);
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);
  try {
    const body = await req.json().catch(() => ({}));
    const billId = Number(body.bill_id);
    if (!Number.isInteger(billId) || billId <= 0) return json({ error: "bill_id is required" }, 400);

    const admin = createClient(SB_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
    // test mode: only when a 32+ character key is set in app_secrets (readable by the server only)
    let testMode = false;
    const given = req.headers.get("x-test-key") ?? "";
    if (given.length >= 32) {
      const { data: sec } = await admin.from("app_secrets").select("value").eq("name", "bill_pdf_test_key").maybeSingle();
      testMode = !!sec?.value && sec.value.length >= 32 && sec.value === given;
    }

    const { data: bill, error: be } = await admin.from("bills")
      .select("id, bill_no, share_token, status, created_at, sent_at, confirmed_at, paid_at, payment_method, upi_ref, lead_id, load_id")
      .eq("id", billId).maybeSingle();
    if (be) throw be;
    if (!bill) return json({ error: "Bill not found" }, 404);
    const { data: load } = await admin.from("loads").select("code, driver_id").eq("id", bill.load_id).single();

    if (!testMode) {
      const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
      let uid = "";
      try {
        const { payload } = await jwtVerify(token, JWKS, { issuer: `${SB_URL}/auth/v1` });
        if (payload.role === "authenticated" && typeof payload.sub === "string") uid = payload.sub;
      } catch (_) { /* fall through */ }
      if (!uid) {
        const { data: u } = await admin.auth.getUser(token);
        uid = u?.user?.id ?? "";
      }
      if (!uid) return json({ error: "Please log in again." }, 401);
      if (uid !== load!.driver_id) {
        const { data: prof } = await admin.from("profiles").select("role, active").eq("id", uid).maybeSingle();
        if (!prof || !prof.active || !["hq", "warehouse"].includes(prof.role)) return json({ error: "This bill is not yours." }, 403);
      }
    }
    if (bill.status === "draft") return json({ error: "Lock the bill before making the PDF." }, 400);

    const { data: lead } = await admin.from("leads").select("code, customer_id").eq("id", bill.lead_id).single();
    const { data: customer } = await admin.from("customers").select("name, phone, address, area").eq("id", lead!.customer_id).single();
    const { data: driver } = await admin.from("profiles").select("full_name, vehicle_no, territory, franchise_id").eq("id", load!.driver_id).single();
    let franchise: Record<string, any> | null = null;
    if (driver?.franchise_id) {
      const { data: fr } = await admin.from("franchises").select("name, code").eq("id", driver.franchise_id).maybeSingle();
      franchise = fr ?? null;
    }
    const { data: rows } = await admin.from("bill_items").select("item_id, qty_kg, rate_per_kg, amount").eq("bill_id", billId);
    const { data: names } = await admin.from("scrap_items").select("id, name");
    const nameOf = new Map((names ?? []).map((n: any) => [n.id, n.name]));
    const items = (rows ?? []).map((r: any) => ({ name: nameOf.get(r.item_id) ?? "Item", qty: Number(r.qty_kg), rate: Number(r.rate_per_kg), amount: Number(r.amount) }))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (!items.length) return json({ error: "This bill has no items." }, 400);

    const bytes = await buildPdf({ bill, lead: lead!, load: load!, customer: customer!, driver: driver!, franchise, items });
    const path = `${bill.bill_no}.pdf`;
    const { error: upErr } = await admin.storage.from("bills").upload(path, bytes, { contentType: "application/pdf", upsert: true, cacheControl: "0" });
    if (upErr) throw upErr;
    await admin.from("bills").update({ pdf_path: path }).eq("id", billId);
    const out: Record<string, unknown> = { url: shareLink(bill.share_token), bill_no: bill.bill_no, status: bill.status, bytes: bytes.length };
    if (testMode && body.return_pdf) {
      let bin = ""; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      out.pdf_base64 = btoa(bin);
    }
    return json(out);
  } catch (e) {
    console.error("bill-pdf failed", e);
    return json({ error: "Could not make the PDF bill. Try again." }, 500);
  }
});
