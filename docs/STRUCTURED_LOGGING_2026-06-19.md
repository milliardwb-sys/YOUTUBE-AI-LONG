# Structured logging foundation

Date: 2026-06-19

## What changed

- Added `LOG_LEVEL`.
- Added `JSON_LOGS=true|false`.
- Request logs can now emit JSON lines with:
  - timestamp;
  - level;
  - logger;
  - message;
  - request id;
  - method;
  - path;
  - status code;
  - elapsed milliseconds.
- `/diagnostics` now reports logging configuration.

## Production setup

```env
LOG_LEVEL=INFO
JSON_LOGS=true
```

This is suitable for Docker, cloud log collectors, and hosted observability platforms that parse JSON logs.

## Current limits

- This is structured logging, not full distributed tracing.
- There is no OpenTelemetry exporter yet.
- There are no alert rules or dashboard templates yet.
