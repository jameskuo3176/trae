# Migration verification and baseline

Verified on Windows 11, 2026-08-14 (QoR review overhaul completion pass).
Numbers are local baselines, not production SLOs. Repeat the API baseline with
`python -m pytest -s tests/test_performance_baseline.py`.

## Automated results

- Django `manage.py check`: no issues.
- Pytest: **91 passed** (includes backup/restore syn_qor + migration manifest +
  maintenance lock, gvim protocol handler, weekly review, group/project review).
- Vitest: **34 files / 162 tests passed** (ReviewView focus + source links,
  SourceFileLink, useGvim, useDialogFocus, Dashboard/Admin suites).
- `vue-tsc --noEmit`: passed.
- Vite production build: passed (737 modules).
- ESLint on changed Review/Admin/gvim files: passed.

## Overhaul acceptance (plan sections 5–8)

| Area | Status |
|------|--------|
| Review UI dialog extraction + Tab/Escape focus | Done (`useDialogFocus`) |
| Source paths via `gvim://` / SourceFileLink | Done; server gvim API deprecated (410) |
| Backup manifest schema/migration metadata | Done |
| Restore `*_syn_qor.db` + maintenance lock | Done |
| Admin SnapshotBackupManager restore command UI | Done (no in-request DB overwrite) |
| Docs: WEEKLY_REVIEW_AND_RECOVERY / developer / user | Updated |

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

Largest minified JavaScript chunks (prior baseline; rebuild to refresh):

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
