# Engine image. Build from the repo root (the engine reads ../dictionary):
#   docker build -f engine/Dockerfile -t unclaimed-engine .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app/engine
# Dependencies first (pinned by uv.lock, the same lock the tests run against).
COPY engine/pyproject.toml engine/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY dictionary /app/dictionary
COPY engine/unclaimed_engine ./unclaimed_engine
COPY engine/question_engine ./question_engine
COPY engine/data ./data
ENV PATH=/app/engine/.venv/bin:$PATH
USER nobody
EXPOSE 8000
# Host and port via uvicorn's environment variables, so a deployment can override them
# (in AWS the engine listens on localhost only: infra/deploy.sh).
ENV UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000
CMD ["uvicorn", "unclaimed_engine.app:app"]
