FROM python:3.13-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# backend lives in telegram-platform/ root as package `backend`
COPY ./requirements.txt /app/requirements.txt
RUN pip install --target=/app/dependencies -r requirements.txt

FROM python:3.13-slim-bookworm AS release

RUN useradd -m apprunner
USER apprunner

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/dependencies:/app" \
    PATH="/app/dependencies/bin:${PATH}"

WORKDIR /app
COPY --chown=apprunner:apprunner ./backend /app/backend
COPY --chown=apprunner:apprunner ./pyproject.toml /app/pyproject.toml

# fba CLI entry: `fba` is installed with deps; run API via granian
EXPOSE 8000

# 用法见 deploy/docker-compose.yml:api / task-worker / scheduler 共用此镜像
CMD ["fba", "run", "--host", "0.0.0.0", "--port", "8000", "--no-reload", "--workers", "2"]
