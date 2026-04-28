FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/common ./packages/common
COPY runtimes/agent-base ./runtimes/agent-base

RUN uv sync --frozen --package agent-base --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Default pod kind; overridden per Deployment via env.
ENV RUNTIME_KIND=compiled_graph
ENV BUNDLE_CACHE_DIR=/var/cache/agent-bundles

RUN mkdir -p /var/cache/agent-bundles

EXPOSE 8080
CMD ["uvicorn", "agent_base.app:app", "--host", "0.0.0.0", "--port", "8080"]
