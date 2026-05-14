#!/bin/bash
cd "$(dirname "$0")"
exec venv/bin/gunicorn \
  --certfile        cert.pem \
  --keyfile         key.pem \
  --bind            0.0.0.0:5000 \
  --workers         2 \
  --timeout         120 \
  --access-logfile  logs/access.log \
  --error-logfile   logs/error.log \
  --capture-output \
  app:app
