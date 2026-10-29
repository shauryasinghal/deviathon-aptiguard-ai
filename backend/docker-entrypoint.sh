#!/bin/sh
# Migrate; seed synthetic demo data only if DEMO_SEED=true AND the database is empty; then serve.
set -eu
alembic upgrade head
if [ "${DEMO_SEED:-false}" = "true" ]; then
  COUNT=$(python -c "import sys;sys.path.insert(0,'.');from sqlalchemy import func,select;from app.db.session import SessionLocal;from app.models import Question;print(SessionLocal().scalar(select(func.count()).select_from(Question)) or 0)")
  if [ "$COUNT" = "0" ]; then python /srv/scripts/seed_demo.py; fi
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
