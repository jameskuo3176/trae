# Migration verification and baseline

Verified on Windows 11, 2026-08-11. Numbers are local baselines, not production
SLOs. Repeat the API baseline with
`python -m pytest -s tests/test_performance_baseline.py`.

## Automated results

- Django `manage.py check`: no issues.
- Pytest: 20 passed. Coverage includes path-only version derivation, canonical
  module M:N/name validation, repository selection/fallback/mirroring, API v2
  pagination and lazy raw retrieval, liveness/readiness, CSRF, and both
  migration commands' default dry-run.
- ESLint and `vue-tsc --noEmit`: passed.
- Vitest with V8 coverage: 20 files / 81 tests passed; statements 35.24%,
  branches 68.95%, functions 46.35%, lines 35.24%.
- Vite production build: passed (727 modules).
- Playwright: Chromium 5/5, Firefox 5/5, and installed Microsoft Edge channel
  5/5. The authenticated flow mocks same-origin API responses and verifies
  dashboard configuration GET/POST plus DC Picker Apply/Cancel; it is not a
  live production-backend test.

## 5k metadata API baseline

The fixture repository contains 5,000 metadata records. Django's test client
requested the maximum API page of 200 records:

- list response: 3.39 ms
- compact JSON payload: 28,682 bytes
- pagination total: 5,000
- lazy raw request: 2.42 ms for 18,000 content bytes
- list assertions confirm no `content` or `raw_dc_report` field

The fixture and timings are intentionally printed by
`tests/test_performance_baseline.py`. They measure serialization/routing and
in-memory fixture filtering, not Mongo/SQLite network or disk latency.

## Production bundle baseline

Largest minified JavaScript chunks:

- `echarts-vendor`: 1,034.94 kB (343.43 kB gzip)
- `vue-vendor`: 106.32 kB (41.23 kB gzip)
- `axios-vendor`: 48.54 kB (18.63 kB gzip)
- main `index`: 18.95 kB (7.61 kB gzip)
- largest route chunk, `AdminView`: 30.67 kB (9.35 kB gzip)

Vite reports the ECharts chunk above its 500 kB warning threshold. Route and
chart components are already lazy-loaded, but further ECharts import reduction
is the main bundle optimization opportunity.

## Deployment validation

Both Compose YAML files parse and contain service maps. Manual cross-file
inspection confirmed repository-root build contexts, Dockerfile paths, bind
mount destinations, Nginx API/health/static/legacy routes, systemd working and
writable paths, and `start.sh` migration/Gunicorn execution.

Docker/Compose, Bash, Nginx, and systemd validation binaries were unavailable
on this Windows host, so `docker compose config`, image builds, `bash -n`,
`nginx -t`, and `systemd-analyze verify` remain target-host checks. PyYAML was
installed to perform structural Compose parsing.
