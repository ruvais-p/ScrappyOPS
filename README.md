# ScrappyOPS

Scrappy App: collector, warehouse (staff and supervisor) and HQ dashboards, plus the staff monitoring app (Scrappy Field), with one login page and a Django backend.

| Folder | What |
|---|---|
| `backend/` | Django server (replaces Supabase). Start with `backend/README.md` |
| `backend/kwd/` | The staff app (Scrappy Field, Kitchen Waste Digester monitoring): TSO, Zonal Manager, Head Office and franchise screens. See `backend/kwd/README.md` |
| `dashboards/` | The website: login page plus collector, warehouse and HQ dashboards (plain HTML/CSS/JS, no framework) |
| `supabase_sql_reference/` | The original Supabase SQL scripts and edge functions, kept for reference |
| `docs_developer_handover.md` | Product requirements, roles and rules |
| `docs_super_admin_business_intelligence.md` | Super Admin dashboard access, metric definitions and rollback |

Point the dashboards at the backend with `python backend/tools/point_frontend.py dashboards site`.
