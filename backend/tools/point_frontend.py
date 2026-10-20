#!/usr/bin/env python
"""Point the website files at this Django server instead of Supabase.

    python tools/point_frontend.py <scrappy_app folder> <output folder> [--api https://api.example.com]

Without --api the pages call the server they were loaded from (use this when Django serves the website, FRONTEND_DIR).
With --api the pages call that address (use this when the website stays on Cloudflare and Django runs elsewhere; then set
CORS_ALLOWED_ORIGINS on the server to the website's address).

Only the two lines that name the old service are changed in each page. The publishable key is no longer needed
and is blanked. Nothing else in the pages is touched."""
import argparse
import re
import shutil
import sys
from pathlib import Path

URL_RE = re.compile(r"const SUPABASE_URL = '[^']*';")
KEY_RE = re.compile(r"const SUPABASE_KEY = '[^']*';")
PAGES = ["index.html", "collector/index.html", "warehouse/index.html", "hq/index.html"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--api", default="", help="address of the Django server; leave empty for same-site")
    a = ap.parse_args()
    src, out = Path(a.source), Path(a.output)
    if not (src / "index.html").exists():
        sys.exit(f"{src} does not look like the scrappy_app folder (no index.html).")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    api = a.api.rstrip("/")
    for page in PAGES:
        f = out / page
        text = f.read_text(encoding="utf8")
        text, n1 = URL_RE.subn(f"const SUPABASE_URL = '{api}';", text)
        text, n2 = KEY_RE.subn("const SUPABASE_KEY = '';", text)
        if n1 != 1 or n2 != 1:
            sys.exit(f"{page}: expected one SUPABASE_URL and one SUPABASE_KEY line, found {n1} and {n2}.")
        f.write_text(text, encoding="utf8")
        print("updated", page)
    leftovers = [p for p in out.rglob("*.html") if "supabase.co" in p.read_text(encoding="utf8")]
    if leftovers:
        print("WARNING: these pages still mention supabase.co:", ", ".join(str(p.relative_to(out)) for p in leftovers))
    print(f"Done. Pages in {out} now call {api or 'the server they are loaded from'}.")


if __name__ == "__main__":
    main()
