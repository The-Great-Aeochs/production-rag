"""Bound request bodies and record request IDs, duration, and status metrics."""

import json
import logging
import time
import uuid

from prometheus_client import Counter, Histogram

from shared.config import settings

log = logging.getLogger(__name__)
REQUESTS = Counter("rag_http_requests_total", "HTTP requests", ["method", "route", "status"])
DURATION = Histogram(
    "rag_http_duration_seconds", "HTTP duration including streams", ["method", "route"]
)


class RequestMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        async def reject(code):
            body = json.dumps({"detail": "Request body too large"}).encode()
            await tracked_send(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await tracked_send({"type": "http.response.body", "body": body})

        try:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > settings.max_request_bytes:
                    return await reject(413)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, bounded_receive, tracked_send)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = (
                scope["method"]
                if scope["method"] in {"GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD"}
                else "OTHER"
            )
            elapsed = time.monotonic() - started
            REQUESTS.labels(method, route, status).inc()
            DURATION.labels(method, route).observe(elapsed)
            log.info(
                "request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
                request_id,
                method,
                route,
                status,
                elapsed * 1000,
            )
