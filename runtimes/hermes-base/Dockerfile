FROM python:3.12-slim AS vendor

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /src
COPY scripts/vendor-hermes.sh scripts/
COPY scripts/prune-hermes-packages.sh scripts/
COPY vendor/hermes-agent/patches vendor/hermes-agent/patches
RUN mkdir -p vendor/hermes-agent && ./scripts/vendor-hermes.sh
RUN ./scripts/prune-hermes-packages.sh /src/vendor/hermes-agent/src

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/common ./packages/common
COPY runtimes/hermes-base ./runtimes/hermes-base
COPY scripts/prune-hermes-packages.sh scripts/
COPY --from=vendor /src/vendor/hermes-agent/src ./vendor/hermes-agent/src
COPY --from=vendor /src/vendor/hermes-agent/REVISION ./vendor/hermes-agent/REVISION

RUN uv sync --frozen --package hermes-base --no-dev 2>/dev/null || \
    uv sync --package hermes-base --no-dev

RUN uv pip install -e ./vendor/hermes-agent/src
RUN ./scripts/prune-hermes-packages.sh /app/.venv/lib/python3.12/site-packages

ENV PATH="/app/.venv/bin:${PATH}"
ENV RUNTIME_KIND=hermes
ENV HERMES_WORK_DIR=/var/cache/hermes-work

RUN mkdir -p /var/cache/hermes-work

EXPOSE 8080
CMD ["uvicorn", "hermes_base.app:app", "--host", "0.0.0.0", "--port", "8080"]
