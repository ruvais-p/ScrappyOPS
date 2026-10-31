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

## CI/CD

The **ScrappyOPS CI/CD** workflow in `.github/workflows/deploy.yml` runs on pushes to `main` or a manual dispatch from GitHub Actions. It validates the backend Docker build, then deploys to DigitalOcean using the `production` environment, runs Django migrations and system checks, and checks `https://scrappymanager.in/healthz`.

Configure the GitHub Actions secrets `DO_SSH_KEY`, `DO_KNOWN_HOSTS`, `DO_HOST`, and `DO_USER` before running the workflow. A README-only commit pushed to `main` can be used to test the complete pipeline; pushes to feature branches do not trigger it automatically.
