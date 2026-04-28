FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/common ./packages/common
COPY services/auth ./services/auth

RUN uv sync --frozen --package auth --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8080

CMD ["uvicorn", "auth.app:app", "--host", "0.0.0.0", "--port", "8080"]
