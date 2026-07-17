# Phase 10 — backend image (local run). uv for fast, reproducible installs.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

# Install deps first (cached layer), then the app package.
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
