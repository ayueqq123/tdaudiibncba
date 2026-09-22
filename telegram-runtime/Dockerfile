FROM python:3.13-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY ./requirements.txt ./requirements-runtime.txt /app/
RUN pip install --target=/app/dependencies -r requirements.txt -r requirements-runtime.txt

FROM build AS release

RUN useradd -m apprunner
USER apprunner

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY --chown=apprunner: . /app

ENV PYTHONPATH="${PYTHONPATH}:/app/dependencies"

ARG PORT=8000
EXPOSE ${PORT}

# 默认跑 Worker 宿主循环;镜像也含上游 telemirror 代码,需要时可在 compose
# command 覆盖为 python main.py 跑上游入口。
CMD ["python", "-m", "runtime.worker"]