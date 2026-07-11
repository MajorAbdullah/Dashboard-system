#!/usr/bin/env bash
# ─── Explore the dollar-postgres-dev database from the CLI ───────────────────
# Quick schema inspection for any table. Useful during development.
#
# Usage:
#   bash scripts/explore_db.sh products
#   bash scripts/explore_db.sh orders
#   bash scripts/explore_db.sh         # list all tables
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

TABLE="${1:-}"
if [[ -z "$TABLE" ]]; then
  docker exec dollar-postgres-dev psql -U postgres -d onedollarstore -c "
    SELECT table_name,
           (SELECT count(*) FROM information_schema.columns
            WHERE table_schema='public' AND table_name=t.table_name) cols,
           (SELECT n_live_tup FROM pg_stat_user_tables
            WHERE relname=t.table_name) row_estimate
    FROM information_schema.tables t
    WHERE table_schema='public'
    ORDER BY table_name;
  "
else
  echo "=== Schema ==="
  docker exec dollar-postgres-dev psql -U postgres -d onedollarstore -c "\d $TABLE"
  echo ""
  echo "=== Row count ==="
  docker exec dollar-postgres-dev psql -U postgres -d onedollarstore -c "SELECT count(*) FROM \"$TABLE\";"
  echo ""
  echo "=== Sample (5 rows) ==="
  docker exec dollar-postgres-dev psql -U postgres -d onedollarstore -c "SELECT * FROM \"$TABLE\" LIMIT 5;"
fi
