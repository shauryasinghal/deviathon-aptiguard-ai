# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ /srv/backend/
COPY scripts/ /srv/scripts/
COPY data/synthetic/ /srv/data/synthetic/
RUN groupadd --gid 10001 app && useradd --create-home --uid 10001 --gid 10001 app \
    && mkdir -p /srv/backend/var \
    && chown -R app:app /srv/backend/var /srv/data \
    && chmod +x /srv/backend/docker-entrypoint.sh
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=6 \
  CMD ["python", "-c", "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready',timeout=2).status==200 else 1)"]
ENTRYPOINT ["/srv/backend/docker-entrypoint.sh"]
