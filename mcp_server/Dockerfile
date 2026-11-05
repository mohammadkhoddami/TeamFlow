FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TEAMFLOW_MCP_TRANSPORT=streamable-http \
    TEAMFLOW_MCP_HOST=0.0.0.0 \
    TEAMFLOW_MCP_PORT=8765 \
    TEAMFLOW_MCP_PATH=/mcp \
    TEAMFLOW_TRUST_ENV=false

WORKDIR /app
COPY pyproject.toml README.md ./
COPY teamflow_mcp ./teamflow_mcp
RUN pip install .

EXPOSE 8765
ENTRYPOINT ["teamflow-mcp"]
