#!/usr/bin/env bash
# TeamFlow VPS deploy — executed by CI over SSH as root.
#
# Preconditions (copied by CI before this runs):
#   /var/www/teamflow/docker-compose.yml   compose file (only file kept here)
#   /tmp/teamflow.deploy.env               shell exports: IMAGE_TAG + secrets
#   /tmp/teamflow-nginx-flow.conf          host nginx snippet
#
# After a successful deploy this script removes everything else from
# /var/www/teamflow, so the directory contains exactly docker-compose.yml and
# the persistent .env (real values, chmod 600; read by docker compose).
set -euo pipefail

APP_DIR=/var/www/teamflow
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.yml")
SNIPPET=/etc/nginx/snippets/teamflow.conf
ENV_FILE=/tmp/teamflow.deploy.env
NGINX_SRC=/tmp/teamflow-nginx-flow.conf
API_HEALTH=http://127.0.0.1:8020/api/v1/health/ready
WEB_HEALTH=http://127.0.0.1:8030/healthz
MCP_HEALTH=http://127.0.0.1:8040/health

cleanup() { rm -f "$ENV_FILE" "$NGINX_SRC" /tmp/teamflow-deploy.sh; }
trap cleanup EXIT

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${IMAGE_TAG:?missing IMAGE_TAG}"
: "${POSTGRES_PASSWORD:?missing POSTGRES_PASSWORD}"
: "${SECRET_KEY:?missing SECRET_KEY}"
: "${S3_ACCESS_KEY:?missing S3_ACCESS_KEY}"
: "${S3_SECRET_KEY:?missing S3_SECRET_KEY}"
export IMAGE_TAG POSTGRES_PASSWORD SECRET_KEY S3_ACCESS_KEY S3_SECRET_KEY

cd "$APP_DIR"

# Shared mail network: declared `external` by the compose file, so it must
# exist before `docker compose up` or the deploy fails. The mail stack is
# expected to join it with the `mail.arsene.ir` alias.
MAIL_NETWORK="${MAIL_NETWORK:-arsene-mail}"
export MAIL_NETWORK
if ! docker network inspect "$MAIL_NETWORK" >/dev/null 2>&1; then
  echo "==> Creating shared mail network ($MAIL_NETWORK)"
  docker network create "$MAIL_NETWORK" >/dev/null
fi

echo "==> Pulling images ($IMAGE_TAG)"
"${COMPOSE[@]}" pull

echo "==> Applying migrations"
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "==> Rolling out"
"${COMPOSE[@]}" up -d --remove-orphans

wait_for() {
  local url="$1" name="$2" tries="${3:-30}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      echo "    $name ready"
      return 0
    fi
    sleep 2
  done
  echo "$name health check failed ($url)" >&2
  return 1
}

echo "==> Waiting for services"
wait_for "$API_HEALTH" "API" 30
wait_for "$WEB_HEALTH" "web" 15
wait_for "$MCP_HEALTH" "MCP" 30

echo "==> Installing nginx snippet"
if ! cmp -s "$NGINX_SRC" "$SNIPPET"; then
  [ -f "$SNIPPET" ] && cp -a "$SNIPPET" "$SNIPPET.bak"
  cp "$NGINX_SRC" "$SNIPPET"
  if nginx -t; then
    systemctl reload nginx
    rm -f "$SNIPPET.bak"
    echo "    nginx reloaded"
  else
    [ -f "$SNIPPET.bak" ] && mv -f "$SNIPPET.bak" "$SNIPPET"
    nginx -t || true
    echo "nginx config test failed - rolled back" >&2
    exit 1
  fi
else
  echo "    unchanged"
fi

echo "==> Keeping only docker-compose.yml and .env in $APP_DIR"
find "$APP_DIR" -mindepth 1 -maxdepth 1 \
  ! -name docker-compose.yml ! -name .env -exec rm -rf {} +

echo "deploy OK ($IMAGE_TAG)"
