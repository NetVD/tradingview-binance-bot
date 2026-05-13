# Monitoring

Local Prometheus + Grafana stack runs on VPS-2 as part of the
`docker-compose.yml`. Dashboards are exported here.

## Files

- `prometheus.yml` — scrape config for FastAPI, postgres, redis, node.
- `dashboards/` — Grafana JSON dashboards (skeleton, fill in after first
  deploy when real metric names are available).

## Initial dashboard ideas

1. **API overview** — req/s, error rate, p50/p95/p99 latency.
2. **VPS-1 link** — webhook receive rate, proxy call success rate.
3. **Signals** — signals received from VPS-1, push fan-out size, push success.
4. **Tier breakdown** — req/min by user tier.
5. **Host** — CPU, RAM, disk, network.

## Alerts (configure in Grafana Alerting)

| Alert | Condition |
|-------|-----------|
| API 5xx spike | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05` |
| API p95 latency | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.3` |
| VPS-1 webhook stuck | `increase(vps1_webhook_received_total[10m]) == 0` during market hours |
| Disk almost full | `node_filesystem_avail_bytes{fstype!="tmpfs"} / node_filesystem_size_bytes < 0.15` |
| Postgres connections | `pg_stat_activity_count > 90` (out of 100) |
