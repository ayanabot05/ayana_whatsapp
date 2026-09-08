#!/bin/bash
# Start the local dev Postgres (persistent data dir under /root) if it's not already up.
PGBIN=/usr/lib/postgresql/15/bin
if ! pg_isready -h 127.0.0.1 -p 5432 -q 2>/dev/null; then
  su postgres -c "$PGBIN/pg_ctl -D /root/pgdata -l /root/pglog.log -o '-p 5432' start" 2>/dev/null
  sleep 2
fi
pg_isready -h 127.0.0.1 -p 5432
