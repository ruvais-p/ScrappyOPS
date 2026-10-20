"""Optional: serve the website files (the scrappy_app folder) from this same server, so the pages and the data share one
address and no cross-site settings are needed. Set FRONTEND_DIR to the folder. If it is not set, every other address
answers 404 in JSON."""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponsePermanentRedirect

NO_CACHE = {".html", ".webmanifest"}


def serve(request, path):
    root = settings.FRONTEND_DIR
    if not root:
        return HttpResponse('{"message":"Not found"}', status=404, content_type="application/json")
    base = Path(root).resolve()
    if path == "favicon.ico":                       # browsers ask for this by habit; give them the app icon
        path = "icon-192.png"
    target = (base / path).resolve()
    if base != target and base not in target.parents:          # never leave the website folder
        raise Http404()
    if target.is_dir():
        if path and not path.endswith("/"):
            return HttpResponsePermanentRedirect("/" + path + "/")
        target = target / "index.html"
    if not target.is_file():
        return HttpResponse('{"message":"Not found"}', status=404, content_type="application/json")
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    resp = FileResponse(open(target, "rb"), content_type=ctype)
    name = target.name
    if target.suffix in NO_CACHE or name == "sw.js":
        resp["Cache-Control"] = "no-cache"
    else:
        resp["Cache-Control"] = "public, max-age=86400"
    if name == "sw.js":
        resp["Service-Worker-Allowed"] = "/"
    return resp
