#!/usr/bin/env sh
# Operate the production stack (compose.prod.yml with deploy/.env).
#
#   deploy/heinzel.sh up                 build and start, or apply changes
#   deploy/heinzel.sh update             git pull, then up
#   deploy/heinzel.sh ps | logs [svc]    state, logs (follow)
#   deploy/heinzel.sh export             full export into ./backups now
#   deploy/heinzel.sh import FILE [...]  replace all data with an export (--replace, --source-key KEY)
#   deploy/heinzel.sh cli ARGS...        any heinzel command, e.g. cli create-admin --tenant ...
#   deploy/heinzel.sh down               stop (data stays in the volumes)
set -eu
cd "$(dirname "$0")/.."
[ -f deploy/.env ] || { echo "deploy/.env is missing: copy deploy/.env.example and fill it in" >&2; exit 1; }
compose() { docker compose -f compose.prod.yml --env-file deploy/.env "$@"; }

case "${1:-}" in
  up)
    mkdir -p backups && chown 10001 backups 2>/dev/null || true
    compose up -d --build --remove-orphans ;;
  update)
    git pull --ff-only
    "$0" up ;;
  ps) compose ps ;;
  logs) shift; compose logs -f --tail=200 "$@" ;;
  export) compose run --rm backup heinzel export --out /backups ;;
  import)
    [ $# -ge 2 ] || { echo "usage: $0 import FILE [--replace] [--source-key KEY]" >&2; exit 2; }
    file=$(realpath "$2"); shift 2
    compose stop api backup
    compose run --rm -v "$file:/import/export.tar.gz:ro" migrate heinzel import /import/export.tar.gz "$@" \
      || { compose start api backup; exit 1; }
    compose start api backup ;;
  cli) shift; compose run --rm migrate heinzel "$@" ;;
  down) compose down ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
