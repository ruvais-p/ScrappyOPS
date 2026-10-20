// Scrappy · hq-logins  (Supabase Edge Function, deployed as version 2, verify_jwt = false)
// Lets an HQ login create the logins (and profiles) for a franchise's people, and reset a password.
// The caller must be an active HQ user: the token is checked here, then the person is created with the
// server-side admin key. That key never leaves this function. A password is either typed by HQ or made here;
// a made-up password is returned once, never stored or logged. A typed password is never sent back.
// A password reset also signs out any login still open for that person (database function hq_end_sessions).
import { createClient } from "npm:@supabase/supabase-js@2";

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const ANON_ENV = Deno.env.get("SUPABASE_ANON_KEY") ?? "";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json", "Cache-Control": "no-store" } });

const ROLES = ["driver", "warehouse", "supervisor"];
const ALPHA = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"; // no look-alike characters (0 O 1 l I)
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function genPassword(): string {
  const out: string[] = [];
  while (out.length < 12) {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    for (const b of bytes) if (b < 220 && out.length < 12) out.push(ALPHA[b % ALPHA.length]); // 220 = 4 x 55: no modulo bias
  }
  return out.slice(0, 4).join("") + "-" + out.slice(4, 8).join("") + "-" + out.slice(8, 12).join("");
}
const clean = (v: unknown, max = 80) => String(v ?? "").replace(/\s+/g, " ").trim().slice(0, max);

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);
  try {
    const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "").trim();
    if (!token) return json({ error: "Please log in again." }, 401);
    const admin = createClient(SB_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });

    // 1. who is calling? must be an active HQ login
    const { data: who } = await admin.auth.getUser(token);
    const uid = who?.user?.id ?? "";
    if (!uid) return json({ error: "Please log in again." }, 401);
    const { data: me } = await admin.from("profiles").select("role, active").eq("id", uid).maybeSingle();
    if (!me || !me.active || me.role !== "hq") return json({ error: "Only HQ can create logins." }, 403);

    const body = await req.json().catch(() => ({}));
    const action = body.action ?? "create";

    // 2a. reset a password (anyone except HQ logins). HQ may type the new password; if it is left empty one is made.
    if (action === "reset_password") {
      const target = String(body.user_id ?? "");
      if (!UUID.test(target)) return json({ error: "Choose a person." }, 400);
      const { data: prof } = await admin.from("profiles").select("full_name, role, franchise_id").eq("id", target).maybeSingle();
      if (!prof) return json({ error: "Person not found." }, 404);
      if (prof.role === "hq") return json({ error: "HQ passwords cannot be reset from here." }, 403);
      const { data: tu } = await admin.auth.admin.getUserById(target);
      const email = tu?.user?.email ?? "";
      let password = String(body.password ?? "");
      let generated = false;
      if (password === "") { password = genPassword(); generated = true; }
      else if (password.length < 8 || password.length > 72) return json({ error: "A password must be 8 to 72 characters." }, 400);
      const { error: ue } = await admin.auth.admin.updateUserById(target, { password });
      if (ue) return json({ error: /password/i.test(ue.message ?? "") ? ue.message : "Could not reset the password. Try again." }, ue.status && ue.status < 500 ? 400 : 500);
      // the old password may be in someone else's hands: end any login that is still open for this person
      const { error: se } = await admin.rpc("hq_end_sessions", { p_user: target });
      if (se) console.error("hq_end_sessions failed", se.message);
      await admin.from("hq_audit").insert({ by_id: uid, action: "password_reset", ref: prof.full_name, detail: { role: prof.role, set_by_hq: !generated }, franchise_id: prof.franchise_id });
      return json({ results: [{ ok: true, role: prof.role, full_name: prof.full_name, email, ...(generated ? { password } : { password_set_by_hq: true }) }] });
    }

    if (action !== "create") return json({ error: "Unknown action." }, 400);

    // 2b. create logins for a franchise
    const fid = Number(body.franchise_id);
    const people = Array.isArray(body.people) ? body.people : [];
    if (!Number.isInteger(fid) || fid <= 0) return json({ error: "Choose the franchise." }, 400);
    if (people.length < 1 || people.length > 10) return json({ error: "Send between 1 and 10 people." }, 400);
    const { data: fr } = await admin.from("franchises").select("id, code, name, active").eq("id", fid).maybeSingle();
    if (!fr || !fr.active) return json({ error: "That franchise is not active." }, 400);

    // the database function runs as the caller, so its own HQ check and activity log apply
    const apikey = req.headers.get("apikey") || ANON_ENV;
    const userDb = createClient(SB_URL, apikey, { auth: { persistSession: false, autoRefreshToken: false }, global: { headers: { Authorization: `Bearer ${token}` } } });

    const results: Record<string, unknown>[] = [];
    for (const p of people) {
      const role = clean(p.role, 20), full_name = clean(p.full_name), email = clean(p.email, 120).toLowerCase();
      const row: Record<string, unknown> = { role, full_name, email };
      if (!ROLES.includes(role)) { results.push({ ...row, ok: false, error: "Role must be collector, warehouse manager or supervisor." }); continue; }
      if (!full_name) { results.push({ ...row, ok: false, error: "Enter the name." }); continue; }
      if (!EMAIL.test(email)) { results.push({ ...row, ok: false, error: "Enter a valid email address." }); continue; }
      let password = String(p.password ?? "");
      let generated = false;
      if (password === "") { password = genPassword(); generated = true; }
      else if (password.length < 8 || password.length > 72) { results.push({ ...row, ok: false, error: "A password must be 8 to 72 characters." }); continue; }

      const { data: created, error: ce } = await admin.auth.admin.createUser({ email, password, email_confirm: true });
      if (ce || !created?.user) {
        const exists = (ce as any)?.code === "email_exists" || /already.*(registered|exists)/i.test(ce?.message ?? "");
        results.push({ ...row, ok: false, error: exists ? "A login with this email already exists. Use a different email." : "Could not create the login. Check the email and try again." });
        continue;
      }
      const { error: pe } = await userDb.rpc("hq_add_person", {
        p_email: email, p_full_name: full_name, p_role: role, p_franchise: fid,
        p_phone: clean(p.phone, 20) || null, p_territory: clean(p.territory, 60) || null, p_vehicle_no: role === "driver" ? (clean(p.vehicle_no, 20) || null) : null,
      });
      if (pe) {
        await admin.auth.admin.deleteUser(created.user.id); // nothing else refers to this brand-new login yet
        results.push({ ...row, ok: false, error: pe.message });
        continue;
      }
      results.push({ ...row, ok: true, ...(generated ? { password } : { password_set_by_hq: true }) });
    }
    return json({ franchise: { id: fr.id, code: fr.code, name: fr.name }, results });
  } catch (e) {
    console.error("hq-logins failed", (e as Error)?.message);
    return json({ error: "Something went wrong. Try again." }, 500);
  }
});
