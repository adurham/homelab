#!/bin/bash
#
# WARNING: lab-only convenience script.
# Adds a passwordless ("trust") PostgreSQL auth entry scoped to the lab
# subnet (172.16.0.0/24) and opens the listener port in iptables. Do not
# run on shared, internet-reachable, or production hosts.
#
# Auto-detects whichever postgres service is enabled (postgresql-ts on a
# Tanium Server, postgresql-tms on a Module Server). The Ansible play
# ansible/apply_tanium_postgres_trust.yml does the same thing across the
# whole cluster; this script is the per-host fallback.
set -euo pipefail

LAB_SUBNET="172.16.0.0/24"
PG_HBA_LINE="host all all ${LAB_SUBNET} trust"

# Function to get PGDATA and PGPORT from systemd for an enabled service
get_pg_vars() {
    local service_name="$1"

    if ! systemctl is-enabled --quiet "$service_name"; then
        return 1
    fi

    PGDATA=$(systemctl show "$service_name" --property=Environment 2>/dev/null | grep -oP 'PGDATA=\K[^ ]+')
    PGPORT=$(systemctl show "$service_name" --property=Environment 2>/dev/null | grep -oP 'PGPORT=\K\d+')

    if [ -n "$PGDATA" ] && [ -n "$PGPORT" ]; then
        SERVICE="$service_name"
        echo "Using enabled PostgreSQL service: $service_name"
        return 0
    else
        return 1
    fi
}

if ! get_pg_vars "postgresql-ts" && ! get_pg_vars "postgresql-tms"; then
    echo "Error: No enabled PostgreSQL services found. Exiting." >&2
    exit 1
fi

FILE="$PGDATA/pg_hba.conf"
if [ ! -f "$FILE" ]; then
    echo "Error: $FILE does not exist. PostgreSQL might not be fully initialized. Exiting." >&2
    exit 1
fi

# Apply pg_hba entry; record whether we changed it so we know to reload postgres.
HBA_CHANGED=0
if sudo grep -Fqx "$PG_HBA_LINE" "$FILE"; then
    echo "pg_hba.conf already contains lab-subnet trust entry."
else
    echo "$PG_HBA_LINE" | sudo tee -a "$FILE" >/dev/null
    echo "Added lab-subnet trust entry to $FILE."
    HBA_CHANGED=1
fi

# Apply iptables rule (idempotent).
if sudo iptables -C INPUT -p tcp --dport "$PGPORT" -j ACCEPT 2>/dev/null; then
    echo "Port $PGPORT already open in iptables."
else
    sudo iptables -A INPUT -p tcp --dport "$PGPORT" -j ACCEPT
    echo "Opened port $PGPORT in iptables."
fi

# Reload postgres only when pg_hba changed; otherwise the change never takes effect.
if [ "$HBA_CHANGED" -eq 1 ]; then
    echo "Reloading $SERVICE to pick up pg_hba.conf change..."
    sudo systemctl reload "$SERVICE"
    echo "Reload complete."
fi
