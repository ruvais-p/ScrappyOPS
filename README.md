# ScrappyOPS

Scrappy App: collector, warehouse (staff and supervisor) and HQ dashboards, with a Django backend.

| Folder | What |
|---|---|
| `backend/` | Django server (replaces Supabase). Start with `backend/README.md` |
| `dashboards/` | The website: login page plus collector, warehouse and HQ dashboards (plain HTML/CSS/JS, no framework) |
| `supabase_sql_reference/` | The original Supabase SQL scripts and edge functions, kept for reference |
| `docs_developer_handover.md` | Product requirements, roles and rules |

Point the dashboards at the backend with `python backend/tools/point_frontend.py dashboards site`.
