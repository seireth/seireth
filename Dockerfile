FROM node:24.16.0-slim AS dashboard
WORKDIR /src/app/dashboard
RUN npm install --global --ignore-scripts npm@11.13.0
COPY app/dashboard/package.json app/dashboard/package-lock.json app/dashboard/.npmrc ./
RUN npm ci --ignore-scripts --no-fund --no-audit
COPY app/dashboard ./
COPY docs/assets /src/docs/assets
RUN npm run build

FROM python:3.14-slim AS python-build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY app app
COPY --from=dashboard /src/app/dashboard/dist app/dashboard/dist
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.14-slim
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /app/.venv /app/.venv
COPY pyproject.toml /app/pyproject.toml
RUN mkdir /home/seireth && chown 65532:65532 /home/seireth
ENV HOME=/home/seireth
USER 65532:65532
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
