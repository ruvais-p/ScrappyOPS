"""Security checks for the live notification socket."""
import asyncio
import json
from unittest.mock import patch

from unittest import IsolatedAsyncioTestCase

from core import realtime


class RealtimeSecurityTests(IsolatedAsyncioTestCase):
    async def test_revoked_session_stops_notifications(self):
        events = asyncio.Queue()
        sent = []
        await events.put({"type": "websocket.connect"})
        await events.put({"type": "websocket.receive", "text": json.dumps({
            "topic": "realtime:all", "event": "phx_join", "ref": "1",
            "payload": {"access_token": "token", "config": {"postgres_changes": [{"table": "loads"}]}},
        })})

        async def receive():
            return await events.get()

        async def send(event):
            sent.append(event)

        identity = {"uid": "user", "role": "hq", "franchise": None, "exp": 9999999999, "sid": "session"}
        with patch.object(realtime.hub, "ensure_started"), patch.object(realtime, "IDENTITY_CHECK_SECONDS", 0.01), \
             patch.object(realtime, "_identity", side_effect=[identity, None]):
            task = asyncio.create_task(realtime.handle_websocket(
                {"type": "websocket", "path": "/realtime/v1/websocket", "headers": []}, receive, send))
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1)
                self.assertTrue(any('"status":"ok"' in event.get("text", "") for event in sent))
                self.assertEqual(sent[-1], {"type": "websocket.close", "code": 4401})
                self.assertFalse(realtime.hub.clients)
            finally:
                await events.put({"type": "websocket.disconnect"})
                await asyncio.wait_for(task, timeout=1)
