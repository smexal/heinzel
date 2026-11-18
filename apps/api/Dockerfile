# Build context: repository root (the API reads modules/ and tenants/).
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api ./
COPY modules /app/modules
COPY tenants /app/tenants
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 heinzel \
    && mkdir -p /data/files && chown heinzel /data/files
ENV HEINZEL_FILES_DIR=/data/files
USER heinzel
EXPOSE 8000
CMD ["uvicorn", "heinzel_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
