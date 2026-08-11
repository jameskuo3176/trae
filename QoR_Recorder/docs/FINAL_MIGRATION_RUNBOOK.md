# Final Django/Mongo/Vue migration runbook

This is the operational source of truth for the current Django migration.
`MIGRATION_V4.md` is retained only as historical context.

## Canonical modules and versions

`GlobalModule` stores one canonical module name in the default relational
database. Names are Unicode NFKC-normalized, trimmed, case-folded for identity,
must not be blank, and are globally unique by `normalized_name`.
`ProjectModule` is the explicit many-to-many project association. A module may
belong to multiple projects; a project may contain multiple modules.
`LegacyModuleMapping` preserves each `(project_id, legacy_module_id)` mapping so
project-local records remain reversible and API v2 can expose global IDs.

New imports derive `version` only from `full_dir`:

1. Normalize slash direction, repeated separators, and `.` segments.
2. Reject blank paths and any `..` traversal.
3. If a `main` segment has a directly preceding valid `regr_*` segment, use it.
4. Otherwise use the last valid `regr_*` segment.
5. If none exists, reject the import with `version_not_in_path`; there is no
   payload/version fallback.

Examples: `/runs/regr_42/main/cpu` and
`D:\runs\regr_old\x\regr_42\main\cpu` both derive `regr_42`.

## Preflight and coordinated backup

1. Stop uploads and other writers.
2. Record image/code versions and copy `.env` securely.
3. Back up relational databases, uploads, and application backups.
4. Back up Mongo independently:

```bash
mongodump --uri "$MONGODB_URI" --db "$MONGODB_DB" \
  --archive="qor-mongo-$(date +%Y%m%d-%H%M%S).archive.gz" --gzip
python manage.py check --deploy
python manage.py showmigrations
```

For file-backed SQLite, copy `data/` only while writers are stopped (or use the
SQLite backup API). Keep the relational and Mongo backups under one timestamp.
Verify archive readability and restore a sample in a non-production namespace.

## Migration order

Both commands are dry-run by default. Always inspect counts before `--execute`.
Run global-module migration first; Mongo execution refuses records whose local
module has no canonical mapping.

```bash
python manage.py migrate
python manage.py migrate_global_modules
python manage.py migrate_global_modules --execute
python manage.py migrate_sqlite_to_mongo
python manage.py migrate_sqlite_to_mongo --execute
```

Use `--project-id ID` to canary one project. Re-run both dry-runs after
execution. Confirm source/destination counts, API v2 module IDs, list
pagination, and lazy raw-report retrieval before changing persistence mode.

Persistence modes:

- `orm`: relational/project database reads and writes.
- `hybrid`: existing relational import transaction plus Mongo mirror; reads
  prefer Mongo and fall back to ORM.
- `mongo`: existing import flow still commits relational compatibility data and
  mirrors heavy records; API v2 reads Mongo without ORM fallback.

Reviews, users, projects, module metadata, and dashboard configuration remain
relational in every mode.

## Vue cutover

1. Build from repository root context because `frontend-vue/` is a sibling of
   `QoR_Recorder/`.
2. Run lint, type-check, Vitest, production build, and Playwright.
3. Deploy Django/Mongo first and verify `/health/live`, `/health/ready`, and API
   v2 through Nginx.
4. Deploy the Nginx image containing `frontend-vue/dist`.
5. Verify authenticated dashboard data, saved configuration API, Picker
   Apply/Cancel, CSRF-protected writes, and lazy raw reports.
6. Keep `/legacy/dashboard/` available during the acceptance window.

```bash
docker compose build
docker compose up -d
docker compose exec django python manage.py check --deploy
curl -fsS http://localhost/health/live
curl -fsS http://localhost/health/ready
```

## Rollback and restore

Application rollback: stop writers, restore the previous image tags, set
`PERSISTENCE_MODE=orm`, route Nginx to the retained legacy UI if required, and
restart. Do not delete Mongo data merely to roll back reads.

Data rollback: stop all writers, restore the coordinated relational snapshot,
then restore Mongo into an empty database or use `--drop` only after confirming
the target:

```bash
mongorestore --uri "$MONGODB_URI" --db "$MONGODB_DB" \
  --archive=qor-mongo-TIMESTAMP.archive.gz --gzip --drop
```

Restore uploads with the matching snapshot. Run migrations/checks, compare
counts, and smoke-test both UIs before reopening writes. Never use
`docker compose down -v` as a rollback or backup operation.

## Acceptance checklist

- [ ] Coordinated relational, Mongo, upload, and configuration backups verified.
- [ ] Global-module dry-run reviewed, executed, and rechecked.
- [ ] Mongo dry-run has no unmapped module IDs; execution counts match sources.
- [ ] API v2 authentication, pagination, global IDs, and lazy raw data verified.
- [ ] Liveness/readiness and CSRF behavior verified through the reverse proxy.
- [ ] Frontend lint, type-check, unit coverage, production build, and E2E pass.
- [ ] Docker/Compose context, mounts, Nginx routes, systemd paths, and `start.sh`
      verified on the target Linux host.
- [ ] Vue cutover and `/legacy/dashboard/` rollback path smoke-tested.
- [ ] Restore rehearsal and rollback owner/time window recorded.
