FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /srv/backend/
COPY scripts/ /srv/scripts/
COPY data/ /srv/data/
RUN useradd --create-home --uid 10001 app && mkdir -p /srv/backend/var && chown -R app /srv
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready')"
CMD ["/srv/backend/docker-entrypoint.sh"]
