# QoR Recorder production and offline deployment

The production stack is Django/Gunicorn + MongoDB + Nginx/Vue. The canonical
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
docker compose logs -f django nginx mongo
```

`docker-compose.yml` deliberately uses repository root (`..`) as its build
context and `QoR_Recorder/Dockerfile` as its Dockerfile. Docker cannot copy the
sibling `frontend-vue/` source if the context is only `QoR_Recorder/`.

Persistent host directories are:

- `data/`: relational SQLite/global and per-project databases
- `uploads/`: uploaded/review files
- `backups/`: application-created backups
- `mongodbdir/`: MongoDB files (all ignored except its README)

Back up all four directories together while writers are stopped, or use the
application backup plus `mongodump` for a consistent online backup. Never run
`docker compose down -v` as a backup procedure.

The public endpoint is Nginx on `HTTP_PORT` (default 80). Django and MongoDB
have no host port. Nginx serves Vue with history fallback and proxies `/api`,
`/uploads`, `/static`, `/health`, and `/legacy/` to Django.

## Persistence and frontend cutover

`PERSISTENCE_MODE` controls heavy QoR records:

- `orm`: relational/project SQLite only
- `mongo`: MongoDB only for heavy records
- `hybrid`: MongoDB first with ORM compatibility fallback

Reviews and configuration remain relational. Compose defaults to `hybrid`;
set the value explicitly in production. Mongo is `mongodb://mongo:27017`
inside Compose.

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
   `python:3.11-slim`, `nginx:1.27-alpine`, `mongo:7.0`) and export them with
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

Before upgrading, back up relational data, uploads, backups, and MongoDB. Build
new images without stopping the old stack, then run:

```bash
docker compose config
docker compose up -d --build
docker compose exec django python manage.py check --deploy
docker compose ps
```

Rollback by restoring the prior image tags and, if schema/data changed,
restoring the coordinated backup. Nginx configuration can be checked with
`nginx -t`; Compose healthchecks use Python, `mongosh`, and `nginx` binaries
that are present in their respective images, without adding `curl`.
