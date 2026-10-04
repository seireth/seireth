FROM node:24.16.0-slim AS web
WORKDIR /src/app/web
RUN npm install --global --ignore-scripts npm@11.13.0
COPY app/web/package.json app/web/package-lock.json app/web/.npmrc ./
RUN npm ci --ignore-scripts --no-fund --no-audit
COPY app/web ./
COPY docs/assets /src/docs/assets
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

FROM python:3.14-slim AS python-build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY app app
COPY --from=web /src/app/web/dist app/web/dist
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.14-slim
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli \
    && command -v docker \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /app/.venv /app/.venv
RUN mkdir /home/seireth && chown 65532:65532 /home/seireth
ENV HOME=/home/seireth
USER 65532:65532
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
