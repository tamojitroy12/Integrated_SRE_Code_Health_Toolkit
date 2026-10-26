# demo-app

Instrumented sample service for the monitoring pipeline (T-03.01). It exports the standard
OpenTelemetry `http.server.request.duration` histogram over OTLP/HTTP and generates its own
steady traffic (`DEMO_SELF_TRAFFIC_RPS`, default 5) so charts have data immediately.

```bash
docker compose -f deploy/docker-compose.yml --profile demo up -d demo-app

# Inject 60 % 5xx and +500 ms latency for 10 minutes, then clear
curl -X POST http://localhost:8080/admin/fault -H "Authorization: Bearer $DEMO_ADMIN_TOKEN" \
     -H "Content-Type: application/json" -d '{"error_rate":0.6,"latency_seconds":0.5,"ttl_seconds":600}'
curl -X POST http://localhost:8080/admin/clear -H "Authorization: Bearer $DEMO_ADMIN_TOKEN"
```

Register it in the Toolkit as service `demo-app`, environment `dev` (or run `toolkit seed-demo`).
