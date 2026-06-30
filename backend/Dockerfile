# SpacePad backend — production image (multi-stage).
#
# Stage 1 builds the dependencies + app into an isolated venv; stage 2 is a slim
# runtime that copies only that venv and the source, runs as a non-root user, and
# serves via a production uvicorn invocation (no --reload).
#
# IMPORTANT: a single process only. CRDT collaboration rooms are held in-memory
# per process (see README "How real-time works"), so running multiple workers
# would split a pad's room across processes and break live sync. Scale by adding a
# shared Y store / Redis pub-sub + sticky routing first — do NOT just bump workers.

# ---- builder ---------------------------------------------------------------- #
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN python -m venv /opt/venv && pip install --upgrade pip
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# Installs runtime deps + the app package (no dev/test extras).
RUN pip install .

# ---- runtime ---------------------------------------------------------------- #
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
# Non-root runtime user.
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
USER app
EXPOSE 8000

# Container-level healthcheck hitting the readiness endpoint (checks DB connectivity).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status==200 else 1)"

# Single process (see note above). Migrations are NOT run here — run
# `alembic upgrade head` against the direct connection as a separate deploy step.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
