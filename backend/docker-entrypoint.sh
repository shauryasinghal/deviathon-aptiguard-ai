#!/bin/sh
# Start-up order: migrate (fail hard) -> reference data -> optional demo seed (only DEMO_SEED=true, empty DB) -> serve.
# Any failure stops the container with a non-zero exit code; nothing continues against a half-initialised database.
set -eu
cd /srv/backend
echo "aptiguard: applying database migrations"
alembic upgrade head
python -m app.bootstrap
if [ "${DEMO_SEED:-false}" = "true" ]; then
  COUNT=$(python -c "from sqlalchemy import func,select;from app.db.session import SessionLocal;from app.models import Question;print(SessionLocal().scalar(select(func.count()).select_from(Question)) or 0)")
  if [ "$COUNT" = "0" ]; then
    echo "aptiguard: DEMO_SEED=true and database empty -> seeding synthetic demo data"
    python /srv/scripts/seed_demo.py
  else
    echo "aptiguard: database already contains $COUNT questions -> demo seed skipped"
  fi
fi
echo "aptiguard: starting API"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" --timeout-graceful-shutdown 20
