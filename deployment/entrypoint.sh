#!/bin/sh
set -eu
case "${1:-serve}" in
  serve)
    exec gunicorn backend.wsgi:app --bind 0.0.0.0:8000 \
      --workers "${WEB_WORKERS:-2}" --threads "${WEB_THREADS:-4}" \
      --timeout "${WEB_TIMEOUT:-45}" --graceful-timeout "${WEB_GRACEFUL_TIMEOUT:-30}" \
      --access-logfile - --error-logfile -
    ;;
  migrate)
    exec python -m alembic upgrade head
    ;;
  *) echo 'Unsupported release command' >&2; exit 2 ;;
esac
