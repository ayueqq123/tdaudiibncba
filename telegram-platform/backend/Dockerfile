FROM python:3.13-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# backend lives in telegram-platform/ root as package `backend`
COPY ./requirements.txt /app/requirements.txt
# `-e .` 行是项目本体,不经 pip 安装——release 阶段 COPY backend + PYTHONPATH 提供
RUN grep -v '^-e ' requirements.txt > requirements-deps.txt \
    && pip install --target=/app/dependencies -r requirements-deps.txt \
    # session_import 子进程在 control-api 内运行(GPL 边界:spawn 不 import);
    # 它只需 telethon——与 telegram-runtime/requirements.txt 的钉死版本保持一致(AGENTS.md §3)
    && pip install --target=/app/dependencies telethon==1.44.0

# 预装插件依赖:plugin/*/requirements.txt 装进镜像后,_requirements_installed 命中,
# 运行时不再调 uv install_requirements(镜像内无 uv 也不应依赖网络)
COPY ./backend/plugin /tmp/plugin
RUN set -e; for f in /tmp/plugin/*/requirements.txt; do \
      [ -f "$f" ] && pip install --target=/app/dependencies -r "$f" || true; \
    done

FROM python:3.13-slim-bookworm AS release

RUN useradd -m apprunner \
    # 具名卷继承镜像目录属主:导入存储/日志目录须预建为 apprunner 可写
    && mkdir -p /var/lib/tg-imports /app/backend/log \
    && chown -R apprunner:apprunner /var/lib/tg-imports /app/backend/log
USER apprunner

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/dependencies:/app" \
    PATH="/app/dependencies/bin:${PATH}"

WORKDIR /app
COPY --from=build --chown=apprunner:apprunner /app/dependencies /app/dependencies
COPY --chown=apprunner:apprunner ./backend /app/backend
COPY --chown=apprunner:apprunner ./pyproject.toml /app/pyproject.toml

# fba CLI 是项目内 cappa 入口(未 pip 安装),生产直接 granian 拉起 backend.main:app
EXPOSE 8000
CMD ["python", "-m", "granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "backend.main:app"]
