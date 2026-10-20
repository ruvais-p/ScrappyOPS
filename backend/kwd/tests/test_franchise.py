from datetime import timedelta

from core.services.common import fetch_one
from kwd.rules.util import ist_today
from kwd.tests.base import KwdCase


class FranchiseTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()
        self.products = {p["code"]: p for p in self.ho.select("fr_products", "*", order=[["sort", True]])}
        self.kwd160 = self.products["KWD-160"]["id"]
        self.inoc = self.products["INOC-1"]["id"]

    def lead(self, franchise=None, name="Green Residency", **kw):
        return self.ho.insert("fr_leads", {"franchise_id": franchise or self.fr_id, "customer_name": name, "customer_type": "private",
                                            "phone": "9446000001", "product_id": self.kwd160, "qty": 2, **kw}, select="*", single=True)

    def stock(self, who, product, qty, kind="received", note=None):
        return who.insert("fr_stock_moves", {"franchise_id": who.fr_id if hasattr(who, "fr_id") else self.fr_id, "product_id": product, "qty": qty, "kind": kind, "note": note}, select="*", single=True)

    def sell(self, who=None, lead=None, items=None, received=0, **kw):
        who = who or self.fr
        args = dict(p_lead=lead, p_customer_name="Green Residency", p_customer_type="private", p_phone="9446000001", p_district=self.ekm,
                    p_place="Kakkanad", p_sale_date=str(ist_today()), p_invoice_no="INV-1", p_amount_received=received,
                    p_items=items if items is not None else [{"product_id": self.kwd160, "qty": 2, "unit_price": 5880}])
        args.update(kw)
        return who.rpc("fr_record_sale", **args)

    # ------------------------------------------------------------------ products, leads
    def test_products_and_people(self):
        self.assertEqual(len(self.fr.select("fr_products", "id")), 8)
        self.assertEqual(self.tso.select("fr_products", "id"), [])
        self.assertEqual(self.fr.select("fr_franchises", "id, business_name"), [{"id": str(self.fr_id), "business_name": "Fran Traders"}])
        self.assertEqual(len(self.ho.select("fr_franchises", "id")), 2)
        self.fr.fails("row-level security", self.fr.insert, "fr_products", {"code": "X", "name": "X", "category": "digester"})
        self.ho.update("fr_products", {"list_price": 5880}, [["eq", "code", "KWD-160"]])
        self.ho.update("fr_products", {"list_price": 5880}, [["eq", "code", "KWD-120"]])

    def test_ho_hands_out_leads_and_the_franchisee_works_them(self):
        ld = self.lead(status="won", lost_reason="x", fr_note="x")                      # the starting state is set by the system
        self.assertEqual((ld["status"], ld["lost_reason"], ld["assigned_by"]), ("new", None, str(self.ho_id)))
        self.fr.fails("row-level security", self.fr.insert, "fr_leads", {"franchise_id": self.fr_id, "customer_name": "Self", "customer_type": "private"})
        self.assertEqual(len(self.fr.select("fr_leads", "id")), 1)
        self.assertEqual(self.fr2.select("fr_leads", "id"), [])
        self.assertEqual(self.zm.select("fr_leads", "id"), [])
        upd = self.fr.update("fr_leads", {"status": "contacted", "fr_note": "Spoke to the owner", "customer_name": "Hacked", "qty": 99}, [["eq", "id", ld["id"]]], select="*")[0]
        self.assertEqual((upd["status"], upd["customer_name"], upd["qty"]), ("contacted", "Green Residency", 2))
        self.fr.fails("Record the sale to close this lead", self.fr.update, "fr_leads", {"status": "won"}, [["eq", "id", ld["id"]]])
        self.fr.fails("cannot go back to New", self.fr.update, "fr_leads", {"status": "new"}, [["eq", "id", ld["id"]]])
        self.fr.fails("why this lead was lost", self.fr.update, "fr_leads", {"status": "lost", "lost_reason": "no"}, [["eq", "id", ld["id"]]])
        lost = self.fr.update("fr_leads", {"status": "lost", "lost_reason": "Bought from a competitor"}, [["eq", "id", ld["id"]]], select="status, lost_reason")[0]
        self.assertEqual(lost["status"], "lost")
        events = self.fr.select("fr_lead_events", "from_status, to_status", [["eq", "lead_id", ld["id"]]], order=[["id", True]])
        self.assertEqual([(e["from_status"], e["to_status"]) for e in events], [("new", "contacted"), ("contacted", "lost")])
        # Head Office can move a lost lead to another franchisee, but cannot edit what the franchisee reports
        moved = self.ho.update("fr_leads", {"franchise_id": self.fr2_id, "status": "new", "fr_note": "wiped"}, [["eq", "id", ld["id"]]], select="franchise_id, status, fr_note")[0]
        self.assertEqual((moved["franchise_id"], moved["status"], moved["fr_note"]), (str(self.fr2_id), "lost", "Spoke to the owner"))
        self.assertEqual(self.fr.select("fr_leads", "id"), [])

    # ------------------------------------------------------------------ stock and sales
    def test_stock_rules(self):
        self.fr.fails("Add a short note", self.stock, self.fr, self.kwd160, 1, "damaged")
        self.fr.fails("Sales move stock automatically", self.stock, self.fr, self.kwd160, 1, "sale")
        self.assertEqual(self.stock(self.fr, self.kwd160, -10, "opening")["qty"], 10)                       # sign is set by the kind
        self.fr.fails("below zero (on hand: 10)", self.stock, self.fr, self.kwd160, 11, "damaged", "Cracked in transit")
        dam = self.stock(self.fr, self.kwd160, 3, "damaged", "Cracked in transit")
        self.assertEqual(dam["qty"], -3)
        # a franchisee can only move their own stock, whatever they send
        mine = self.fr.insert("fr_stock_moves", {"franchise_id": self.fr2_id, "product_id": self.inoc, "qty": 5, "kind": "received"}, select="franchise_id", single=True)
        self.assertEqual(mine["franchise_id"], str(self.fr_id))
        self.tso.fails("Not allowed", self.tso.insert, "fr_stock_moves", {"franchise_id": self.fr_id, "product_id": self.inoc, "qty": 1, "kind": "received"})
        st = {r["product_id"]: r for r in self.fr.select("v_fr_stock", "*")}
        self.assertEqual((st[self.kwd160]["on_hand"], st[self.kwd160]["received"], st[self.kwd160]["adjusted"]), (7, 10, -3))
        self.assertEqual(self.fr2.select("v_fr_stock", "*"), [])
        self.assertEqual(len(self.ho.select("v_fr_stock", "*")), 2)

    def test_record_sale_moves_stock_and_closes_the_lead(self):
        ld = self.lead()
        self.fr.fails("Only 0 of Kitchen Waste Digester 160 L in stock", self.sell, lead=ld["id"])
        self.stock(self.fr, self.kwd160, 5, "opening")
        self.stock(self.fr, self.inoc, 20, "opening")
        self.tso.fails("Only a franchisee", self.sell, self.tso)
        self.fr.fails("Add at least one product", self.sell, items=[])
        self.fr.fails("Enter the customer name", self.sell, p_customer_name=" ")
        self.fr.fails("Choose the customer type", self.sell, p_customer_type="alien")
        self.fr.fails("within the last 7 days", self.sell, p_sale_date=str(ist_today() - timedelta(days=9)))
        self.fr.fails("Enter the selling price", self.sell, items=[{"product_id": self.kwd160, "qty": 1, "unit_price": 0}])
        self.fr.fails("more than the sale total", self.sell, received=99999)
        self.fr.fails("Lead not found", self.sell, lead="00000000-0000-0000-0000-000000000000")
        sid = self.sell(lead=ld["id"], received=5000, items=[{"product_id": self.kwd160, "qty": 2, "unit_price": 5880}, {"product_id": self.inoc, "qty": 3, "unit_price": 100}])
        sale = self.fr.select("fr_sales", "*, fr_sale_items(qty, unit_price, line_total)", [["eq", "id", sid]])[0]
        self.assertEqual((sale["total"], sale["amount_received"], sale["payment_status"]), (2 * 5880 + 300, 5000, "partial"))
        self.assertEqual((sale["needs_install"], sale["installation_status"], sale["status"], sale["flags"]), (True, "pending", "active", []))
        self.assertEqual(sorted(i["line_total"] for i in sale["fr_sale_items"]), [300, 11760])
        st = {r["product_id"]: r["on_hand"] for r in self.fr.select("v_fr_stock", "*")}
        self.assertEqual((st[self.kwd160], st[self.inoc]), (3, 17))
        self.assertEqual(self.fr.select("fr_leads", "status", [["eq", "id", ld["id"]]]), [{"status": "won"}])
        self.fr.fails("already has a sale", self.sell, lead=ld["id"])
        self.fr.fails("Only 3 of Kitchen Waste Digester 160 L", self.sell, items=[{"product_id": self.kwd160, "qty": 4, "unit_price": 5880}])
        self.assertEqual(len(self.fr.select("fr_sales", "id")), 1)                       # the refused sale left nothing behind
        self.assertEqual(self.fr2.select("fr_sales", "id"), [])
        self.assertEqual(self.ho.select("v_fr_sold", "qty, line_total", [["eq", "product_id", self.inoc]]), [{"qty": 3, "line_total": 300}])
        self.assertEqual(self.ho.select("audit_log", "action", [["eq", "table_name", "fr_sales"]]), [{"action": "INSERT"}])

    def test_flags_for_backdated_and_cheap_sales(self):
        self.ho.update("fr_products", {"list_price": 5880}, [["eq", "id", self.kwd160]])
        self.stock(self.fr, self.kwd160, 5, "opening")
        sid = self.sell(p_sale_date=str(ist_today() - timedelta(days=3)), items=[{"product_id": self.kwd160, "qty": 1, "unit_price": 4000}])
        self.assertEqual(self.fr.select("fr_sales", "flags", [["eq", "id", sid]])[0]["flags"], ["backdated", "below_list_price"])

    def test_delivery_and_installation_follow_the_rules(self):
        self.stock(self.fr, self.kwd160, 5, "opening")
        sid = self.sell(items=[{"product_id": self.kwd160, "qty": 1, "unit_price": 5880}], received=1000)
        f = lambda **v: self.fr.update("fr_sales", v, [["eq", "id", sid]], select="*")[0]
        self.fr.fails("cannot be reduced", f, amount_received=500)
        self.fr.fails("more than the sale total", f, amount_received=9999)
        self.fr.fails("Mark the sale delivered before", f, installation_status="scheduled", install_planned_on=str(ist_today()))
        self.assertEqual(f(amount_received=5880, invoice_no="INV-9")["payment_status"], "paid")
        out = f(delivery_status="dispatched")
        self.assertEqual((out["delivery_status"], out["dispatched_on"]), ("dispatched", str(ist_today())))
        self.fr.fails("Enter the delivery date", f, delivery_status="delivered")
        self.fr.fails("Delivery date must be between", f, delivery_status="delivered", delivered_on=str(ist_today() + timedelta(days=2)))
        self.fr.fails("Delivery cannot go backwards", f, delivery_status="pending")
        out = f(delivery_status="delivered", delivered_on=str(ist_today()))
        self.assertEqual((out["delivery_status"], out["delivered_at"] is not None), ("delivered", True))
        self.fr.fails("Enter the installation date", f, installation_status="scheduled")
        self.assertEqual(f(installation_status="scheduled", install_planned_on=str(ist_today()))["installation_status"], "scheduled")
        self.fr.fails("Enter the date it was installed", f, installation_status="installed")
        self.fr.fails("photo of the installed unit", f, installation_status="installed", installed_on=str(ist_today()))
        done = f(installation_status="installed", installed_on=str(ist_today()), install_photo=self.fr.upload())
        self.assertEqual((done["installation_status"], done["installed_at"] is not None), ("installed", True))
        self.assertEqual(f(installation_status="scheduled", install_note="After install")["installation_status"], "installed")     # only the note can change now
        # the money, the lines and the totals cannot be edited
        keep = f(total=1, status="cancelled", customer_name="Hacked", ho_flag=True)
        self.assertEqual((keep["total"], keep["status"], keep["customer_name"], keep["ho_flag"]), (5880, "active", "Green Residency", False))

    def test_head_office_cancels_and_flags_sales(self):
        self.stock(self.fr, self.kwd160, 5, "opening")
        ld = self.lead()
        sid = self.sell(lead=ld["id"])
        self.fr.fails("Only Head Office", self.fr.rpc, "fr_cancel_sale", p_sale=str(sid), p_reason="changed my mind")
        self.ho.fails("Say why this sale is cancelled", self.ho.rpc, "fr_cancel_sale", p_sale=str(sid), p_reason="no")
        self.ho.fails("Say why you are flagging", self.ho.update, "fr_sales", {"ho_flag": True, "ho_flag_reason": "x"}, [["eq", "id", sid]])
        flagged = self.ho.update("fr_sales", {"ho_flag": True, "ho_flag_reason": "Price looks wrong"}, [["eq", "id", sid]], select="ho_flag, total")[0]
        self.assertEqual(flagged, {"ho_flag": True, "total": 2 * 5880})
        self.ho.rpc("fr_cancel_sale", p_sale=str(sid), p_reason="Customer returned the units")
        self.ho.fails("Already cancelled", self.ho.rpc, "fr_cancel_sale", p_sale=str(sid), p_reason="Customer returned the units")
        self.assertEqual(self.fr.select("v_fr_stock", "on_hand")[0]["on_hand"], 5)                         # stock is back
        self.assertEqual(self.fr.select("fr_leads", "status", [["eq", "id", ld["id"]]]), [{"status": "negotiating"}])
        self.fr.fails("cancelled by Head Office", self.fr.update, "fr_sales", {"amount_received": 100}, [["eq", "id", sid]])
        self.assertEqual(self.ho.select("v_fr_sold", "qty"), [])                                            # cancelled sales are not counted

    # ------------------------------------------------------------------ presentations and targets
    def test_presentations(self):
        ld = self.lead()
        when = (ist_today() + timedelta(days=2)).isoformat() + "T10:00:00+05:30"
        p = self.fr.insert("fr_presentations", {"franchise_id": self.fr2_id, "lead_id": ld["id"], "scheduled_at": when, "venue_type": "lsgd",
                                                 "venue_name": "Thrikkakara Municipality", "status": "done", "outcome": "interested"}, select="*", single=True)
        self.assertEqual((p["franchise_id"], p["status"], p["outcome"]), (str(self.fr_id), "scheduled", None))
        self.assertEqual(self.fr.select("fr_leads", "status", [["eq", "id", ld["id"]]]), [{"status": "presentation_set"}])
        self.fr.fails("Enter the place", self.fr.insert, "fr_presentations", {"scheduled_at": when, "venue_type": "other", "venue_name": " "})
        other = self.lead(franchise=self.fr2_id, name="Not Mine")
        self.fr.fails("not yours", self.fr.insert, "fr_presentations", {"lead_id": other["id"], "scheduled_at": when, "venue_type": "other", "venue_name": "Hall"})
        self.tso.fails("row-level security", self.tso.insert, "fr_presentations", {"scheduled_at": when, "venue_type": "other", "venue_name": "Hall"})
        re = self.fr.update("fr_presentations", {"scheduled_at": (ist_today() + timedelta(days=3)).isoformat() + "T11:00:00+05:30", "venue_name": "Hall B",
                                                  "status": "scheduled"}, [["eq", "id", p["id"]]], select="reschedule_count, venue_name")[0]
        self.assertEqual(re, {"reschedule_count": 1, "venue_name": "Hall B"})
        self.fr.fails("only on the day", self.fr.update, "fr_presentations", {"status": "done", "outcome": "interested", "actual_attendees": 20}, [["eq", "id", p["id"]]])
        fetch_one("update kwd_fr_presentations set scheduled_at = now() - interval '1 hour' where id = %(i)s returning 1", {"i": p["id"]})
        self.fr.fails("Choose how it went", self.fr.update, "fr_presentations", {"status": "done"}, [["eq", "id", p["id"]]])
        self.fr.fails("how many people attended", self.fr.update, "fr_presentations", {"status": "done", "outcome": "interested"}, [["eq", "id", p["id"]]])
        done = self.fr.update("fr_presentations", {"status": "done", "outcome": "interested", "actual_attendees": 25, "done_photo": self.fr.upload()}, [["eq", "id", p["id"]]], select="status, done_at")[0]
        self.assertEqual(done["status"], "done")
        self.assertEqual(self.fr.select("fr_leads", "status", [["eq", "id", ld["id"]]]), [{"status": "negotiating"}])
        self.assertEqual(self.fr2.update("fr_presentations", {"notes": "x"}, [["eq", "id", p["id"]]], select="id"), [])
        self.assertEqual(self.fr2.select("fr_presentations", "id"), [])

    def test_targets_are_head_office_only(self):
        month = ist_today().replace(day=1).isoformat()
        t = self.ho.insert("fr_targets", {"franchise_id": self.fr_id, "month": month, "target_units": 10, "target_amount": 60000}, select="*", single=True)
        self.assertEqual(t["set_by"], str(self.ho_id))
        self.fr.fails("row-level security", self.fr.insert, "fr_targets", {"franchise_id": self.fr_id, "month": month, "target_units": 1})
        self.assertEqual(len(self.fr.select("fr_targets", "id")), 1)
        self.assertEqual(self.fr2.select("fr_targets", "id"), [])
        self.assertEqual(self.fr.update("fr_targets", {"target_units": 1}, [["eq", "id", t["id"]]], select="id"), [])
        self.ho.fails("", self.ho.insert, "fr_targets", {"franchise_id": self.fr_id, "month": (ist_today().replace(day=1) + timedelta(days=3)).isoformat()})   # not the 1st
        self.ho.q("fr_targets", "delete", filters=[["eq", "id", t["id"]]])
        self.assertEqual(self.ho.select("fr_targets", "id"), [])
