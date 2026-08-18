# BuildKit is enabled by Docker Desktop; avoid `# syntax=docker/dockerfile:1.7`
# so offline/flaky Hub auth cannot block the first build stage.
# Build from the repository root, not QoR_Recorder:
#   docker build -f QoR_Recorder/Dockerfile --target django-runtime .
# This is required because the canonical Vue source is the sibling
# frontend-vue directory.

ARG NODE_IMAGE=node:20-alpine
ARG PYTHON_IMAGE=python:3.11-slim
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS frontend-builder
ARG NPM_OFFLINE=0
WORKDIR /src/frontend-vue
COPY frontend-vue/package.json frontend-vue/package-lock.json ./
# BuildKit's cache can be pre-populated for an air-gapped build; npm ci never
# runs in a runtime container and package-lock.json makes the result repeatable.
RUN --mount=type=cache,target=/root/.npm \
    if [ "$NPM_OFFLINE" = "1" ]; then \
        npm ci --offline --no-audit --no-fund; \
    else \
        npm ci --no-audit --no-fund; \
    fi
COPY frontend-vue/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS python-builder
ARG PIP_OFFLINE=0
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY QoR_Recorder/requirements.txt ./
COPY QoR_Recorder/wheelhouse/ /wheelhouse/
# For an air-gapped build, pre-populate a pip cache or replace this layer with
# a wheelhouse-backed install as documented in deploy/README.md.
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$PIP_OFFLINE" = "1" ]; then \
        pip install --no-index --find-links=/wheelhouse -r requirements.txt; \
    else \
        pip install -r requirements.txt; \
    fi

FROM ${PYTHON_IMAGE} AS django-runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=django_app.settings \
    HOST=0.0.0.0 \
    PORT=8000 \
    DEBUG=0
WORKDIR /app
COPY --from=python-builder /opt/venv /opt/venv
COPY QoR_Recorder/ ./
RUN mkdir -p /app/data /app/uploads /app/backups /app/static \
    && DB_TYPE=sqlite PERSISTENCE_MODE=orm python manage.py collectstatic --noinput
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn django_app.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile -"]

FROM ${NGINX_IMAGE} AS frontend-runtime
COPY QoR_Recorder/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-builder /src/frontend-vue/dist/ /usr/share/nginx/html/
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["nginx", "-t"]
