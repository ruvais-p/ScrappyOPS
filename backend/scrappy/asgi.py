"""Run with:  uvicorn scrappy.asgi:application --host 0.0.0.0 --port 8000 --workers 4
Serves the normal pages and data through Django, and the live-update websocket (/realtime/v1/websocket) itself."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scrappy.settings")
django_app = get_asgi_application()

from core.realtime import handle_websocket  # noqa: E402  (needs Django to be set up first)


async def application(scope, receive, send):
    kind = scope["type"]
    if kind == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif kind == "websocket":
        if scope["path"].rstrip("/") == "/realtime/v1/websocket":
            await handle_websocket(scope, receive, send)
        else:
            await send({"type": "websocket.close", "code": 4404})
    else:
        await django_app(scope, receive, send)
