FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-install-project --no-dev

# Copy only application files, not local credentials, uploads, or databases.
COPY main.py auth.py config.py database.py models.py schemas.py image_utils.py email_utils.py ./
COPY routers/ ./routers/
COPY templates/ ./templates/
COPY static/ ./static/
COPY alembic.ini ./
COPY alembic/ ./alembic/
RUN uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN useradd --uid 10001 --user-group --create-home appuser
COPY --from=builder /bin/uv /bin/uv
COPY --from=builder --chown=appuser:appuser /app /app
# /media remains mounted by the app even when S3 is configured.
RUN mkdir -p /app/media/profile_pics && chown -R appuser:appuser /app/media

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PORT=8080 \
    FORWARDED_ALLOW_IPS=127.0.0.1
USER appuser
EXPOSE 8080
# exec delivers shutdown signals to the server. Cloud Run supplies PORT.
CMD ["/bin/sh", "-c", "exec uv run --locked --no-sync --no-dev fastapi run main.py --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
