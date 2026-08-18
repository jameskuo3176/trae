# QoR Recorder production and offline deployment

> **中文运维手册**（Ubuntu 部署、Makefile 上传、前台/后台、可视化、升级）：
> [`docs/OPERATIONS.md`](../docs/OPERATIONS.md)

The production stack is Django/Gunicorn + PostgreSQL + MongoDB + Nginx/Vue. The canonical
Vue source is the repository-level `frontend-vue/` directory. The image build
copies its compiled `dist/` into the Nginx image; it does not create another
source tree.

## Docker Compose

Run Compose from `QoR_Recorder/`:

```bash
cp .env.example .env
# Set SECRET_KEY, ALLOWED_HOSTS and (for HTTPS) CSRF_TRUSTED_ORIGINS.
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f django nginx postgres mongo
```

`docker-compose.yml` deliberately uses repository root (`..`) as its build
context and `QoR_Recorder/Dockerfile` as its Dockerfile. Docker cannot copy the
sibling `frontend-vue/` source if the context is only `QoR_Recorder/`.

Persistent host directories are:

- `postgres_data` named volume: Django users/projects/permissions/review metadata
- `data/`: retained legacy SQLite inputs only; the default runtime does not create project DB files
- `uploads/`: uploaded/review files
- `backups/`: application-created backups
- `mongodbdir/`: MongoDB files (all ignored except its README)

Back up PostgreSQL with `pg_dump`, Mongo with `mongodump`, and uploads together
while writers are stopped (or under a coordinated snapshot). Never run
`docker compose down -v` as a backup procedure.

The public endpoint is Nginx on `HTTP_PORT` (default 80). Django and MongoDB
have no host port. Nginx serves Vue with history fallback and proxies `/api`,
`/uploads`, `/static`, `/health`, and `/legacy/` to Django.

## Persistence and frontend cutover

Two layers (do not conflate `DB_TYPE` with heavy-record storage):

| Layer | Store | Contents |
|-------|-------|----------|
| Django ORM (`DB_TYPE`) | PostgreSQL (Compose default) | Users, projects, permissions, module metadata, reviews, dashboard config |
| Heavy QoR (`PERSISTENCE_MODE`) | MongoDB (Compose default `mongo`) | Records, raw reports, violations, run notes |

`PERSISTENCE_MODE` values:

- `mongo` (**Compose default**): API v2 reads Mongo; project SQLite creation/routing is disabled
- `orm`: relational/project SQLite only (no Mongo)
- `hybrid`: Mongo-first reads with ORM fallback; best-effort Mongo mirror — **cutover only**, not a long-term default

Django does not use Mongo as a full ORM primary database (no djongo). Compose uses
`DB_TYPE=sql` (PostgreSQL) for metadata and `PERSISTENCE_MODE=mongo` for heavy data. Mongo
URI inside Compose is `mongodb://mongo:27017`.

After stopping writers and backing up SQLite, migrate the main metadata database,
then canonical modules and project heavy rows:

```bash
docker compose exec django python manage.py migrate
docker compose exec django python manage.py migrate_sqlite_metadata_to_postgres --source /app/data/qor_recorder.db
docker compose exec django python manage.py migrate_sqlite_metadata_to_postgres --source /app/data/qor_recorder.db --execute
docker compose exec django python manage.py migrate_project_metadata_to_postgres
docker compose exec django python manage.py migrate_project_metadata_to_postgres --execute
docker compose exec django python manage.py migrate_global_modules
docker compose exec django python manage.py migrate_global_modules --execute
docker compose exec django python manage.py migrate_sqlite_to_mongo
docker compose exec django python manage.py migrate_sqlite_to_mongo --execute
```

See `docs/FINAL_MIGRATION_RUNBOOK.md` and `docs/OPERATIONS.md`.

Vue is the default production frontend. The Django template is intentionally
retained at `/legacy/dashboard/` for rollback verification. `FRONTEND_MODE`
records the selected mode for systemd/direct deployments; changing Compose
back to a fully legacy UI also requires an Nginx routing change. Test the
legacy URL before every frontend cutover and do not delete `dashboard.html`
until the migration is formally accepted.

## Reverse proxy, sessions, and CSRF

Keep browser and API requests on the same origin. Nginx forwards the original
host, client address, and `X-Forwarded-Proto`; Django trusts that scheme header.
For HTTPS set:

```dotenv
ALLOWED_HOSTS=qor.example.internal
CSRF_TRUSTED_ORIGINS=https://qor.example.internal
SESSION_COOKIE_SECURE=1
SECURE_SSL_REDIRECT=1
# Enable only after HTTPS is verified:
SECURE_HSTS_SECONDS=31536000
```

`CSRF_TRUSTED_ORIGINS` entries must include the scheme. The Vue client sends
the `csrftoken` cookie as `X-CSRFToken`. TLS ingress must overwrite, rather
than append untrusted, forwarded headers. Do not publish Gunicorn directly.

For host Nginx/systemd deployment, build `frontend-vue` and copy only `dist/`
to a web root such as `/var/www/qor-recorder`; adapt `deploy/nginx.conf` by
changing its upstream from `django:8000` to `127.0.0.1:8000`.

## systemd deployment

Create `/opt/qor_recorder/venv`, install dependencies ahead of time, copy the
application to `/opt/qor_recorder`, and configure `.env`. Then:

```bash
sudo install -m 0644 deploy/qor_recorder.service /etc/systemd/system/
sudo chown -R qor:qor /opt/qor_recorder
sudo systemctl daemon-reload
sudo systemctl enable --now qor_recorder
sudo journalctl -u qor_recorder -f
```

`start.sh` performs `python manage.py migrate --noinput` and then execs
Gunicorn. It intentionally never installs packages or downloads assets.

## Air-gapped workflow

There are no CDN or runtime package downloads. Prepare artifacts on a connected
machine with the same CPU architecture and OS family:

1. Pull the pinned base/service images (`node:20-alpine`,
   `python:3.11-slim`, `nginx:1.27-alpine`, `postgres:16-alpine`, `mongo:7.0`) and export them with
   `docker save`.
2. Build `qor-recorder-django` and `qor-recorder-web` while package registries
   are available, then export those final images. This is the preferred and
   most reproducible offline deployment.
3. Transfer the image archive, repository deployment files, `.env`, and data;
   import with `docker load`, then run `docker compose up -d --no-build`.

If images must be built inside the air gap, pre-populate BuildKit's npm and pip
caches before disconnecting. Put a Python wheelhouse in
`QoR_Recorder/wheelhouse/`:

```bash
python -m pip download -r QoR_Recorder/requirements.txt \
  -d QoR_Recorder/wheelhouse
```

For npm, populate the cache using the committed lock file and verify it:

```bash
cd frontend-vue
npm ci --ignore-scripts
npm cache verify
npm ci --offline
```

Then build with strict offline switches:

```bash
docker compose build \
  --build-arg PIP_OFFLINE=1 \
  --build-arg NPM_OFFLINE=1
```

Do not assume an empty cache or incomplete wheelhouse can satisfy an offline
build. Import the Mongo image before Compose starts; Compose must not pull from
a registry in the offline environment.

## Upgrade and checks

Before upgrading, run `pg_dump`, `mongodump`, and back up uploads plus retained
legacy SQLite inputs. Build
new images without stopping the old stack, then run:

```bash
docker compose config
docker compose up -d --build
docker compose exec django python manage.py check --deploy
docker compose ps
```

Project SQLite databases must be migrated with the reconciliation command:

```bash
python manage.py migrate_project_databases --check
python manage.py migrate_project_databases
```

The command audits every configured project schema before writing, refuses
incompatible existing columns/constraints, closes Django connections, and
creates verified SQLite online-backup copies under
`DATA_DIR/migration-backups/project-migration-<timestamp>/` before any pending
change. It validates historical project tables before recording legacy
migration history, creates only missing compatible tables, applies normal
pending migrations, and verifies that pre-existing row counts are unchanged.
Rerunning it with no pending work is read-only and does not create another
backup.

Flask-era databases may contain `NULL` in the otherwise non-nullable
`qor_records.source_file`, `release_dir`, and `version_description` columns.
After reviewing the reported counts and semantics, explicitly opt into the
targeted normalization:

```bash
python manage.py migrate_project_databases \
  --normalize-legacy-nulls
```

Normalization runs after all selected project databases have been backed up,
updates only `NULL` values in those three columns to empty strings inside one
transaction per database, and aborts if the counts changed after the audit.

Rollback by restoring the prior image tags and, if schema/data changed,
restoring the coordinated backup. Nginx configuration can be checked with
`nginx -t`; Compose healthchecks use Python, `mongosh`, and `nginx` binaries
that are present in their respective images, without adding `curl`.
