FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

WORKDIR /app

ARG UV_INDEX_GITHUB_PASSWORD
ENV UV_INDEX_GITHUB_USERNAME=x-access-token \
    UV_INDEX_GITHUB_PASSWORD=${UV_INDEX_GITHUB_PASSWORD}

COPY deploy/examples/custom-image/path-graph-rag-mcp/app.py .

RUN uv pip install --system --no-cache \
    "path-graph @ https://github.com/yoosungung/path-graph/releases/download/v0.1.4/path_graph-0.1.4-py3-none-any.whl" \
    "fastapi>=0.115" "uvicorn[standard]>=0.32"

ENV RUNTIME_POOL=mcp:custom:path-graph-rag-v1

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
