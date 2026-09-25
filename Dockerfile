FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli \
    && command -v docker \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY app app
RUN uv sync --locked --no-dev --no-editable --no-cache
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
