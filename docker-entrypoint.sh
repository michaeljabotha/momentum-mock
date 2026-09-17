#!/bin/sh
# Seed the database if it isn't there - covers the case where /app/momentum.db is
# shadowed by a mounted volume. A database baked in at build time is left alone.
set -e
if [ ! -f /app/momentum.db ]; then
    echo "momentum.db not found - seeding..."
    python -m app.seed
fi
exec "$@"
