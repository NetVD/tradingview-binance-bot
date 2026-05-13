"""
Prometheus instrumentation.

We expose:
  - http_requests_total{method,path,status}
  - http_request_duration_seconds{method,path}
  - vps1_webhook_received_total{symbol,recommendation}
  - vps1_proxy_call_total{endpoint,status}
"""

from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

vps1_webhook_received_total = Counter(
    "vps1_webhook_received_total",
    "Webhooks received from VPS-1",
    ["symbol", "recommendation"],
)

vps1_proxy_call_total = Counter(
    "vps1_proxy_call_total",
    "Calls proxied to VPS-1",
    ["endpoint", "status"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        # Use the route template (e.g. /api/v2/signals/{signal_id}) so cardinality
        # stays bounded even with millions of distinct signal IDs.
        path_template = request.url.path
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            http_requests_total.labels(request.method, path_template, "500").inc()
            raise
        else:
            route = request.scope.get("route")
            if route is not None and getattr(route, "path", None):
                path_template = route.path
            http_requests_total.labels(request.method, path_template, str(status_code)).inc()
            http_request_duration_seconds.labels(request.method, path_template).observe(
                time.perf_counter() - start
            )
            return response
