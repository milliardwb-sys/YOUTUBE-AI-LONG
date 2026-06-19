# Observability Metrics Foundation Update - 2026-06-19

This update closes a practical slice of the production backlog item "observability: logs, metrics, traces, alerts".

## Implemented

- Existing JSON metrics endpoint remains available:
  - `GET /observability/metrics`
- New Prometheus-compatible endpoint:
  - `GET /observability/metrics/prometheus`
- Metrics exposed:
  - total HTTP requests;
  - total/max request latency in milliseconds;
  - requests by status code;
  - total project count;
  - project count by status;
  - total job count;
  - job count by status;
  - usage event count;
  - estimated usage cost in cents.
- Prometheus labels intentionally avoid dynamic request paths to reduce cardinality.

## Still Not Production-Complete

- Metrics are in-process and reset on restart.
- There is no OpenTelemetry tracing yet.
- There is no external log sink yet.
- There are no alert rules, dashboards, or SLO burn-rate alerts yet.
- Multi-instance aggregation requires Prometheus scraping each instance or a managed telemetry pipeline.
