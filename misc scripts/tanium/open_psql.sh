#!/bin/bash

# Function to get PGDATA and PGPORT from systemd for an enabled service
get_pg_vars() {
    local service_name="$1"

    # Check if the service is **enabled** (ignore active status)
    if ! systemctl is-enabled --quiet "$service_name"; then
        return 1  # Skip this service if it's not enabled
    fi

    PGDATA=$(systemctl show "$service_name" --property=Environment 2>/dev/null | grep -oP 'PGDATA=\K[^ ]+')
    PGPORT=$(systemctl show "$service_name" --property=Environment 2>/dev/null | grep -oP 'PGPORT=\K\d+')

    if [ -n "$PGDATA" ] && [ -n "$PGPORT" ]; then
        echo "Using enabled PostgreSQL service: $service_name"
        return 0
    else
        return 1  # PGDATA or PGPORT not found
    fi
}

# Try finding an **enabled** PostgreSQL service
if get_pg_vars "postgresql-ts"; then
    SERVICE_NAME="postgresql-ts"
elif get_pg_vars "postgresql-tms"; then
    SERVICE_NAME="postgresql-tms"
else
    echo "Error: No enabled PostgreSQL services found. Exiting."
    exit 1
fi

# Define the path to pg_hba.conf
FILE="$PGDATA/pg_hba.conf"
LINE="host all all 0.0.0.0/0 trust"  # Replace with the exact line you want to ensure is present

# Ensure pg_hba.conf exists before modifying it
if [ ! -f "$FILE" ]; then
    echo "Error: $FILE does not exist. PostgreSQL might not be fully initialized. Exiting."
    exit 1
fi

# Function to check and modify pg_hba.conf
update_pg_hba() {
    if grep -Fqx "$LINE" "$FILE"; then
        echo "The line is already present in $FILE."
    else
        echo "$LINE" >> "$FILE"
        echo "The line has been added to $FILE."
    fi
}

# Function to check and open the PostgreSQL port in iptables
update_iptables() {
    if sudo iptables -C INPUT -p tcp --dport "$PGPORT" -j ACCEPT 2>/dev/null; then
        echo "Port $PGPORT is already open in iptables."
    else
        echo "Adding iptables rule to allow incoming connections on port $PGPORT..."
        sudo iptables -A INPUT -p tcp --dport "$PGPORT" -j ACCEPT
        echo "Port $PGPORT is now open."
    fi
}

# Run the functions
update_pg_hba
update_iptables
