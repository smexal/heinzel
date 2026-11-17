FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api ./
COPY modules /app/modules
COPY tenants /app/tenants
RUN uv sync --frozen --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "heinzel_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
