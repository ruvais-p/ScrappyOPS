"""CORS for the dashboards. The pages call this server with an Authorization header, so the browser asks first (OPTIONS).
Set CORS_ALLOWED_ORIGINS to the address of the website (for example https://scrappy-manager.example.com). If the
website is served by this same server, CORS is not used at all."""
from django.conf import settings
from django.http import HttpResponse

ALLOW_HEADERS = "authorization, apikey, content-type, prefer, x-client-info, x-test-key, accept-profile, content-profile, range"
ALLOW_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"


class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _origin_ok(self, origin):
        allowed = settings.CORS_ALLOWED_ORIGINS
        return bool(origin) and ("*" in allowed or origin in allowed)

    def __call__(self, request):
        origin = request.headers.get("Origin", "")
        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Method"):
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if self._origin_ok(origin):
            allowed = settings.CORS_ALLOWED_ORIGINS
            response["Access-Control-Allow-Origin"] = "*" if "*" in allowed else origin
            if "*" not in allowed:
                response["Vary"] = "Origin"
            response["Access-Control-Allow-Headers"] = ALLOW_HEADERS
            response["Access-Control-Allow-Methods"] = ALLOW_METHODS
            response["Access-Control-Expose-Headers"] = "Content-Range, Content-Disposition"
            response["Access-Control-Max-Age"] = "86400"
        return response
