"""What the KWD module's tables look like to the pages: names, columns, links between tables, and who may read which rows
(the old database's row-level security, as Python). The pages use the original table names (visits, field_days ...);
in the database each is prefixed kwd_.

Column types: u uuid, t text, i integer, n numeric, f float, b boolean, ts timestamptz, d date, a text[], ua uuid[], j jsonb."""


def cols(spec):
    return dict(p.split(":") for p in spec.split())


TYPES = {"u": "uuid", "t": "text", "i": "bigint", "n": "numeric", "f": "double precision", "b": "boolean", "ts": "timestamptz",
         "d": "date", "a": "text[]", "ua": "uuid[]", "j": "jsonb"}

# api name -> (database table, columns, generated columns that cannot be written)
TABLES = {
    "districts": ("kwd_districts", cols("id:i name:t"), set()),
    "profiles": ("kwd_profiles", cols("id:u full_name:t email:t phone:t role:t manager_id:u is_active:b created_at:ts"), set()),
    "user_districts": ("kwd_user_districts", cols("user_id:u district_id:i"), set()),
    "lsgds": ("kwd_lsgds", cols("id:u name:t type:t district_id:i office_lat:f office_lng:f assigned_tso:u created_at:ts"), set()),
    "contacts": ("kwd_contacts", cols("id:u lsgd_id:u name:t designation:t phone:t email:t is_decision_maker:b verified_by:u verified_at:ts created_by:u created_at:ts"), set()),
    "tasks": ("kwd_tasks", cols("id:u lsgd_id:u assigned_to:u assigned_by:u planned_date:d purpose:t status:t created_at:ts"), set()),
    "visits": ("kwd_visits", cols("id:u task_id:u lsgd_id:u tso_id:u check_in_at:ts check_in_lat:f check_in_lng:f gps_accuracy_m:f distance_from_office_m:f "
                                  "check_out_at:ts photo_path:t discussion:t outcome:t interest_level:i next_followup_on:d fraud_flags:a zm_status:t zm_remark:t "
                                  "zm_reviewed_by:u zm_reviewed_at:ts ho_remark:t ho_signed_by:u ho_signed_at:ts created_at:ts details_at:ts"), set()),
    "visit_contacts": ("kwd_visit_contacts", cols("visit_id:u contact_id:u"), set()),
    "opportunities": ("kwd_opportunities", cols("id:u lsgd_id:u financial_year:t owner_id:u stage:t expected_units:i unit_price:n expected_value:n probability:i "
                                                "expected_close:d plan_project_no:t work_order_no:t lost_reason:t updated_at:ts"), {"expected_value"}),
    "followups": ("kwd_followups", cols("id:u lsgd_id:u opportunity_id:u contact_id:u visit_id:u assigned_to:u due_on:d mode:t notes:t done_at:ts done_note:t created_at:ts"), set()),
    "verification_calls": ("kwd_verification_calls", cols("id:u contact_id:u visit_id:u called_by:u confirmed:b remark:t called_at:ts outcome:t"), set()),
    "audit_log": ("kwd_audit_log", cols("id:i table_name:t row_id:u action:t old_data:j new_data:j actor:u at:ts"), set()),
    "expense_policy": ("kwd_expense_policy", cols("id:i rate_two_wheeler:n rate_car:n da_local:n da_outstation:n da_min_visits:i lodging_cap:n auto_taxi_cap_day:n "
                                                  "bill_required_above:n max_km_day:i road_factor:n km_tolerance_pct:i claim_window_days:i updated_by:u updated_at:ts"), set()),
    "expense_payments": ("kwd_expense_payments", cols("id:u tso_id:u month:d days:i amount:n paid_ref:t note:t paid_by:u paid_at:ts"), set()),
    "field_days": ("kwd_field_days", cols("id:u tso_id:u day:d travel_mode:t vehicle_no:t start_at:ts start_lat:f start_lng:f start_acc:f start_odo:i start_photo:t "
                                          "end_at:ts end_lat:f end_lng:f end_acc:f end_odo:i end_photo:t night_halt:b halt_place:t tso_note:t visits_count:i gps_km:n "
                                          "odo_km:i ta_km:n ta_amount:n da_amount:n lodging_amount:n other_amount:n total_claimed:n flags:a status:t submitted_at:ts "
                                          "approved_amount:n zm_by:u zm_at:ts zm_remark:t ho_by:u ho_at:ts ho_remark:t paid_by:u paid_at:ts paid_ref:t created_at:ts "
                                          "payment_id:u ho_flag:b ho_flag_by:u ho_flag_at:ts da_requested:n"), {"total_claimed"}),
    "expense_items": ("kwd_expense_items", cols("id:u day_id:u tso_id:u category:t amount:n description:t from_place:t to_place:t bill_no:t bill_path:t bill_hash:t flags:a created_at:ts"), set()),
    "claim_events": ("kwd_claim_events", cols("id:i day_id:u actor:u event:t amount:n note:t meta:j at:ts"), set()),
    "fr_franchises": ("kwd_fr_franchises", cols("id:u user_id:u business_name:t district_id:i territory:t address:t gstin:t is_active:b created_at:ts"), set()),
    "fr_product_categories": ("kwd_fr_product_categories", cols("key:t name:t sort:i"), set()),
    "fr_products": ("kwd_fr_products", cols("id:u code:t name:t category:t spec:t unit:t list_price:n hsn_sac:t gst_percent:n needs_install:b is_active:b sort:i"), set()),
    "fr_leads": ("kwd_fr_leads", cols("id:u franchise_id:u customer_name:t customer_type:t contact_person:t phone:t district_id:i place:t address:t product_id:u qty:i "
                                      "hq_note:t status:t lost_reason:t next_followup_on:d fr_note:t last_update_at:ts assigned_by:u assigned_at:ts created_at:ts source:t"), set()),
    "fr_lead_events": ("kwd_fr_lead_events", cols("id:i lead_id:u franchise_id:u actor:u from_status:t to_status:t note:t at:ts"), set()),
    "fr_presentations": ("kwd_fr_presentations", cols("id:u franchise_id:u lead_id:u scheduled_at:ts venue_type:t venue_name:t lsgd_name:t district_id:i address:t "
                                                      "contact_person:t phone:t expected_attendees:i product_ids:ua purpose:t status:t reschedule_count:i cancel_reason:t "
                                                      "done_at:ts actual_attendees:i outcome:t notes:t done_lat:f done_lng:f done_photo:t created_by:u created_at:ts"), set()),
    "fr_sales": ("kwd_fr_sales", cols("id:u franchise_id:u lead_id:u customer_name:t customer_type:t phone:t district_id:i place:t sale_date:d invoice_no:t total:n "
                                      "amount_received:n payment_status:t needs_install:b delivery_status:t dispatched_on:d delivered_on:d delivered_at:ts delivery_note:t "
                                      "installation_status:t install_planned_on:d installed_on:d installed_at:ts install_note:t install_photo:t flags:a status:t "
                                      "cancel_reason:t cancelled_by:u cancelled_at:ts ho_flag:b ho_flag_reason:t created_by:u created_at:ts"), {"payment_status"}),
    "fr_sale_items": ("kwd_fr_sale_items", cols("id:u sale_id:u product_id:u hsn_sac:t qty:i unit_price:n gst_percent:n gst_amount:n line_total:n"), {"gst_amount", "line_total"}),
    "fr_stock_moves": ("kwd_fr_stock_moves", cols("id:u franchise_id:u product_id:u qty:i kind:t sale_id:u ref_no:t note:t created_by:u created_at:ts"), set()),
    "fr_targets": ("kwd_fr_targets", cols("id:u franchise_id:u month:d product_id:u target_units:i target_amount:n set_by:u updated_at:ts"), set()),
    "fr_company_settings": ("kwd_fr_company_settings", cols("id:i company_name:t address:t phone:t gstin:t email:t state:t updated_by:u updated_at:ts"), set()),
    "fr_payment_receipts": ("kwd_fr_payment_receipts", cols("id:u sale_id:u amount:n method:t reference:t received_by:u received_at:ts"), set()),
    "fr_meetings": ("kwd_fr_meetings", cols("id:u scheduled_at:ts meeting_type:t description:t status:t created_by:u created_at:ts completed_by:u completed_at:ts"), set()),
}

# views the pages read (computed from the rows the caller may see; see engine.VIEWS)
VIEW_COLUMNS = {
    "v_pipeline": cols("district:t stage:t lsgds:i units:i value:n weighted_value:n"),
    "v_staff_daily": cols("tso_id:u full_name:t day:d visits:i lsgds:i flagged:i verified:i ho_signed:i"),
    "v_overdue_followups": cols("id:u lsgd_id:u opportunity_id:u contact_id:u visit_id:u assigned_to:u due_on:d mode:t notes:t done_at:ts done_note:t created_at:ts lsgd_name:t"),
    "v_shared_contact_phones": cols("phone:t lsgds:i names:a"),
    "v_fr_sold": cols("franchise_id:u sale_id:u sale_date:d month:d product_id:u qty:i line_total:n"),
    "v_fr_stock": cols("franchise_id:u product_id:u on_hand:i received:i sold:i adjusted:i last_move_at:ts"),
}

# foreign keys, used to resolve embedded selects:  (child table, child column, parent table, constraint name)
FKS = [
    ("claim_events", "actor", "profiles", "claim_events_actor_fkey"), ("claim_events", "day_id", "field_days", "claim_events_day_id_fkey"),
    ("contacts", "created_by", "profiles", "contacts_created_by_fkey"), ("contacts", "lsgd_id", "lsgds", "contacts_lsgd_id_fkey"),
    ("contacts", "verified_by", "profiles", "contacts_verified_by_fkey"),
    ("expense_items", "day_id", "field_days", "expense_items_day_id_fkey"), ("expense_items", "tso_id", "profiles", "expense_items_tso_id_fkey"),
    ("expense_payments", "paid_by", "profiles", "expense_payments_paid_by_fkey"), ("expense_payments", "tso_id", "profiles", "expense_payments_tso_id_fkey"),
    ("expense_policy", "updated_by", "profiles", "expense_policy_updated_by_fkey"),
    ("field_days", "ho_by", "profiles", "field_days_ho_by_fkey"), ("field_days", "ho_flag_by", "profiles", "field_days_ho_flag_by_fkey"),
    ("field_days", "paid_by", "profiles", "field_days_paid_by_fkey"), ("field_days", "payment_id", "expense_payments", "field_days_payment_id_fkey"),
    ("field_days", "tso_id", "profiles", "field_days_tso_id_fkey"), ("field_days", "zm_by", "profiles", "field_days_zm_by_fkey"),
    ("followups", "assigned_to", "profiles", "followups_assigned_to_fkey"), ("followups", "contact_id", "contacts", "followups_contact_id_fkey"),
    ("followups", "lsgd_id", "lsgds", "followups_lsgd_id_fkey"), ("followups", "opportunity_id", "opportunities", "followups_opportunity_id_fkey"),
    ("followups", "visit_id", "visits", "followups_visit_id_fkey"),
    ("fr_franchises", "district_id", "districts", "fr_franchises_district_id_fkey"), ("fr_franchises", "user_id", "profiles", "fr_franchises_user_id_fkey"),
    ("fr_lead_events", "lead_id", "fr_leads", "fr_lead_events_lead_id_fkey"),
    ("fr_leads", "assigned_by", "profiles", "fr_leads_assigned_by_fkey"), ("fr_leads", "district_id", "districts", "fr_leads_district_id_fkey"),
    ("fr_leads", "franchise_id", "fr_franchises", "fr_leads_franchise_id_fkey"), ("fr_leads", "product_id", "fr_products", "fr_leads_product_id_fkey"),
    ("fr_presentations", "district_id", "districts", "fr_presentations_district_id_fkey"),
    ("fr_presentations", "franchise_id", "fr_franchises", "fr_presentations_franchise_id_fkey"), ("fr_presentations", "lead_id", "fr_leads", "fr_presentations_lead_id_fkey"),
    ("fr_sale_items", "product_id", "fr_products", "fr_sale_items_product_id_fkey"), ("fr_sale_items", "sale_id", "fr_sales", "fr_sale_items_sale_id_fkey"),
    ("fr_sales", "district_id", "districts", "fr_sales_district_id_fkey"), ("fr_sales", "franchise_id", "fr_franchises", "fr_sales_franchise_id_fkey"),
    ("fr_sales", "lead_id", "fr_leads", "fr_sales_lead_id_fkey"),
    ("fr_stock_moves", "franchise_id", "fr_franchises", "fr_stock_moves_franchise_id_fkey"), ("fr_stock_moves", "product_id", "fr_products", "fr_stock_moves_product_id_fkey"),
    ("fr_stock_moves", "sale_id", "fr_sales", "fr_stock_moves_sale_id_fkey"),
    ("fr_targets", "franchise_id", "fr_franchises", "fr_targets_franchise_id_fkey"), ("fr_targets", "product_id", "fr_products", "fr_targets_product_id_fkey"),
    ("lsgds", "assigned_tso", "profiles", "lsgds_assigned_tso_fkey"), ("lsgds", "district_id", "districts", "lsgds_district_id_fkey"),
    ("opportunities", "lsgd_id", "lsgds", "opportunities_lsgd_id_fkey"), ("opportunities", "owner_id", "profiles", "opportunities_owner_id_fkey"),
    ("profiles", "manager_id", "profiles", "profiles_manager_id_fkey"),
    ("tasks", "assigned_by", "profiles", "tasks_assigned_by_fkey"), ("tasks", "assigned_to", "profiles", "tasks_assigned_to_fkey"),
    ("tasks", "lsgd_id", "lsgds", "tasks_lsgd_id_fkey"),
    ("user_districts", "district_id", "districts", "user_districts_district_id_fkey"), ("user_districts", "user_id", "profiles", "user_districts_user_id_fkey"),
    ("verification_calls", "called_by", "profiles", "verification_calls_called_by_fkey"),
    ("verification_calls", "contact_id", "contacts", "verification_calls_contact_id_fkey"), ("verification_calls", "visit_id", "visits", "verification_calls_visit_id_fkey"),
    ("visit_contacts", "contact_id", "contacts", "visit_contacts_contact_id_fkey"), ("visit_contacts", "visit_id", "visits", "visit_contacts_visit_id_fkey"),
    ("visits", "ho_signed_by", "profiles", "visits_ho_signed_by_fkey"), ("visits", "lsgd_id", "lsgds", "visits_lsgd_id_fkey"),
    ("visits", "task_id", "tasks", "visits_task_id_fkey"), ("visits", "tso_id", "profiles", "visits_tso_id_fkey"),
    ("visits", "zm_reviewed_by", "profiles", "visits_zm_reviewed_by_fkey"),
]


def table_of(api):
    return TABLES[api][0] if api in TABLES else "kwd_" + api


def columns_of(api):
    return TABLES[api][1] if api in TABLES else VIEW_COLUMNS[api]
