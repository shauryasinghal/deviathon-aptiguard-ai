#!/usr/bin/env bash
# Container verification (needs Docker Engine + Compose v2.17+). Used by CI; runnable locally where Docker exists.
#   bash scripts/docker_smoke.sh
# 1. demo stack: build, health, migrations, demo seed, nginx proxy + headers, candidate login, workflow call
# 2. restart: data persists, seed not repeated, still healthy
# 3. production stack (PostgreSQL, no demo): no seeding, demo accounts absent, admin bootstrap, audit chain
# 4. must-fail cases: unsafe production config, failed migration (no API start, no seeding)
set -euo pipefail
cd "$(dirname "$0")/.."
API=http://127.0.0.1:8080/api/v1
DEMO="docker compose -p agsmoke"
PROD="docker compose -p agprod -f docker-compose.yml -f docker-compose.prod.yml"
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
# Capture logs first, then search: piping into `grep -q` under pipefail turns a match (SIGPIPE) into a failure.
has_log() { local logs; logs=$($DEMO logs --no-color backend 2>&1); grep -qF -- "$1" <<<"$logs"; }
json() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
cleanup() { $DEMO down -v --remove-orphans >/dev/null 2>&1 || true; $PROD down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1. demo stack"
$DEMO up -d --build --wait --wait-timeout 300
health=$(curl -fsS "$API/health"); grep -qF '"ok"' <<<"$health" || fail "health"
ready=$(curl -fsS "$API/ready")
echo "$ready" | json 'd["status"]' | grep -qx ready || fail "ready: $ready"
[ "$(echo "$ready" | json 'd["questions"]>0')" = "True" ] || fail "demo seed did not run"
hdr=$(curl -fsSI http://127.0.0.1:8080/)
grep -qi "content-security-policy" <<<"$hdr" || fail "CSP header missing"
grep -qi "x-frame-options: DENY" <<<"$hdr" || fail "X-Frame-Options missing"
PW=$(curl -fsS "$API/demo-status" | json 'd["demo_password"]')
TOK=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
      -d "{\"email\":\"candidate1@aptiguard.demo\",\"password\":\"$PW\"}" | json 'd["access_token"]')
curl -fsS -H "Authorization: Bearer $TOK" "$API/assessment/available" | json 'len(d["forms"])' | grep -qx 2 || fail "candidate sees wrong forms"
ATOK=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
       -d "{\"email\":\"admin@aptiguard.demo\",\"password\":\"$PW\"}" | json 'd["access_token"]')
curl -fsS -H "Authorization: Bearer $ATOK" "$API/audit/verify" | json 'd["ok"]' | grep -qx True || fail "audit chain"
[ "$($DEMO exec -T backend id -u)" = "10001" ] || fail "backend not running as non-root user 10001"
has_log "applying database migrations" || fail "migration log line missing"
before=$(echo "$ready" | json 'd["questions"]')

echo "== 2. restart"
$DEMO restart backend
$DEMO up -d --wait --wait-timeout 180
after=$(curl -fsS "$API/ready" | json 'd["questions"]')
[ "$before" = "$after" ] || fail "data changed across restart ($before -> $after)"
has_log "demo seed skipped" || fail "seed not skipped on restart"
if has_log "Traceback"; then fail "traceback in backend logs"; fi
$DEMO down -v --remove-orphans

echo "== 3. production stack (PostgreSQL)"
export JWT_SECRET POSTGRES_PASSWORD ADMIN_PW
JWT_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))")
POSTGRES_PASSWORD=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
ADMIN_PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(18))")
$PROD up -d --build --wait --wait-timeout 300
ready=$(curl -fsS "$API/ready")
[ "$(echo "$ready" | json 'd["questions"]')" = "0" ] || fail "production stack seeded demo data: $ready"
curl -fsS "$API/demo-status" | json '"demo_password" in d or d["demo_mode"]' | grep -qx False || fail "demo exposed in production"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/auth/login" -H 'Content-Type: application/json' \
       -d '{"email":"admin@aptiguard.demo","password":"AptiGuard-Demo-2026"}')
[ "$code" = "401" ] || fail "demo login in production returned $code"
$PROD exec -T -e ADMIN_EMAIL=ops@example.test -e ADMIN_NAME="Ops" -e ADMIN_PASSWORD="$ADMIN_PW" backend python /srv/scripts/create_admin.py
TOK=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
      -d "{\"email\":\"ops@example.test\",\"password\":\"$ADMIN_PW\"}" | json 'd["access_token"]')
curl -fsS -H "Authorization: Bearer $TOK" "$API/dashboard/summary" >/dev/null || fail "admin dashboard"
curl -fsS -H "Authorization: Bearer $TOK" "$API/audit/verify" | json 'd["ok"]' | grep -qx True || fail "audit chain (prod)"
$PROD down -v --remove-orphans

echo "== 4. must-fail cases"
docker compose -p agneg build backend >/dev/null
if docker compose -p agneg run --rm -e APP_ENV=production -e DEMO_MODE=true -e JWT_SECRET="$JWT_SECRET" backend >/tmp/neg1.log 2>&1; then
  fail "unsafe production config started"; fi
grep -q "DEMO_MODE must be false" /tmp/neg1.log || fail "unsafe config: wrong error"
grep -q "$JWT_SECRET" /tmp/neg1.log && fail "secret echoed in logs"
if docker compose -p agneg run --rm -e DATABASE_URL="postgresql+psycopg://nobody@db-does-not-exist:5432/x" backend >/tmp/neg2.log 2>&1; then
  fail "container started despite failed migration"; fi
grep -q "starting API" /tmp/neg2.log && fail "API started after failed migration"
grep -q "seeding synthetic" /tmp/neg2.log && fail "seeded after failed migration"
docker compose -p agneg down -v --remove-orphans >/dev/null 2>&1 || true
echo "DOCKER SMOKE PASSED"
