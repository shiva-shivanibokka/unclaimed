# Simulator image. Build from simulator/: docker build -t unclaimed-simulator simulator
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY simulator ./simulator
ENV PATH=/app/.venv/bin:$PATH
USER nobody
EXPOSE 8090
CMD ["uvicorn", "simulator.app:app", "--host", "0.0.0.0", "--port", "8090", "--proxy-headers"]
