FROM python:3.12-slim

WORKDIR /app

# Build from agents-runtime repo root:
#   make sync-path-graph-docker
#   docker build -f deploy/examples/custom-image/path-graph-rag-mcp/Dockerfile .
COPY path-graph/pipeline /path-graph/pipeline
COPY deploy/examples/custom-image/path-graph-rag-mcp/app.py .

RUN pip install --no-cache-dir /path-graph/pipeline "fastapi>=0.115" "uvicorn[standard]>=0.32"

ENV RUNTIME_POOL=mcp:custom:path-graph-rag-v1

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
