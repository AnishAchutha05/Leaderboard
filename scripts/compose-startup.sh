#!/bin/sh
set -e

echo "[startup] Running database migrations..."
alembic upgrade head

echo "[startup] Bootstrapping seed data (course/verified badges; participants if workbook available)..."
python -m backend.database.bootstrap

echo "[startup] Initialization complete."
