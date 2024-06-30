#!/bin/bash
set -e # Exit on any error

# Check for required tools
for tool in curl jq awk sed; do
    if ! command -v $tool &> /dev/null; then
        echo "Error: $tool is not installed."
        exit 1
    fi
done

source /home/tandev/auth_token.env

# Variables
FQDN=$(hostname -f)
METRICS_URL="https://$FQDN/metrics"
VM_URL="http://172.16.1.16:8428/api/v1/import/prometheus"
TOKEN_VALIDATE_URL="https://$FQDN/api/v2/api_tokens"

# Static labels
TPAN_ACCOUNT="AMD-Enterprises"
TPAN_ENVIRONMENT="Prod"

# Combined labels
LABELS=("tpan_account=\"$TPAN_ACCOUNT\"" "tpan_environment=\"$TPAN_ENVIRONMENT\"" "tpan_server=\"$FQDN\"" "job=\"tanium_server\"" "instance=\"taniumserver1.tanium.local\"")

# Log function
log() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') - $1" >&2
}

# Update the environment variable file with token details
update_env_file() {
    local new_token_response="$1"
    local new_token=$(echo "$new_token_response" | jq -r '.data.token_string')
    local new_token_id=$(echo "$new_token_response" | jq -r '.data.id')

    tmp_file=$(mktemp)
    jq --arg new_token "$new_token" --arg new_token_id "$new_token_id" \
        '.data.token_string = $new_token | .data.id = $new_token_id' \
        /home/tandev/auth_token.json >"$tmp_file" &&
        mv "$tmp_file" /home/tandev/auth_token.json

    export AUTH_TOKEN="$new_token"
    export TOKEN_ID="$new_token_id"
}

# Validate and renew the token if needed
validate_and_renew_token() {
    local response=$(curl -s -k -H "session: $AUTH_TOKEN" "$TOKEN_VALIDATE_URL/$TOKEN_ID")
    if [[ $? -ne 0 || -z "$response" ]]; then
        log "Error: Failed to validate token. Curl response: $response"
        exit 1
    fi

    local expiry=$(echo "$response" | jq -r '.data.expiration')
    if [ -z "$expiry" ];then
        log "Error: Token validation response did not contain an expiration date. Response: $response"
        exit 1
    fi

    local expiry_timestamp=$(date -d "$expiry" +%s)
    local current_time=$(date +%s)
    local time_remaining=$((expiry_timestamp - current_time))

    if ((time_remaining < 3600)); then
        local renew_response=$(curl -s -k -X PATCH -H "Content-Type: application/json" -d "{\"token_string\": \"$AUTH_TOKEN\"}" "$TOKEN_VALIDATE_URL")
        if [[ $? -ne 0 || -z "$renew_response" ]]; then
            log "Error: Failed to renew token. Curl response: $renew_response"
            exit 1
        fi

        local new_token=$(echo "$renew_response" | jq -r '.data.token_string')
        if [[ -z "$new_token" || "$new_token" == "null" ]]; then
            log "Failed to renew auth token. Renew response: $renew_response"
            exit 1
        fi
        
        update_env_file "$renew_response"
    fi
}

# Function to inject or update labels
inject_labels() {
    local metrics="$1"
    local -a labels=("${@:2}")

    local start_time=$(date +%s%N)
    local timestamp=$(date +%s)

    local output=""
    while IFS= read -r line; do
        if [[ "$line" =~ ^# ]]; then
            output+="$line"$'\n'
        else
            local metric_name="${line%%[[:space:]]*}"
            local rest_of_line="${line#*[[:space:]]}"
            local existing_labels="${line#*\{}"
            existing_labels="${existing_labels%\}*}"

            local metric_value="${rest_of_line##* }"

            # Parse existing labels into an associative array
            declare -A label_map
            if [[ "$existing_labels" != "$line" ]]; then
                IFS=',' read -ra label_array <<< "$existing_labels"
                for label in "${label_array[@]}"; do
                    local key="${label%%=*}"
                    label_map["$key"]="${label#*=}"
                done
            fi

            # Inject or update labels
            for new_label in "${labels[@]}"; do
                local key="${new_label%%=*}"
                label_map["$key"]="${new_label#*=}"
            done

            # Reconstruct the label string
            local new_labels="{"
            for key in "${!label_map[@]}"; do
                new_labels+="${key}=${label_map[$key]},"
            done
            new_labels="${new_labels%,}}"

            # Check if the line already has a timestamp
            if [[ "$rest_of_line" =~ [[:space:]][0-9]{10,}$ ]]; then
                output+="${metric_name}${new_labels} ${metric_value}"$'\n'
            else
                if [[ "$existing_labels" == "$line" ]]; then
                    # No existing labels
                    output+="${metric_name}${new_labels} $metric_value $timestamp"$'\n'
                else
                    # Existing labels
                    output+="${metric_name}${new_labels} ${metric_value}"$'\n'
                fi
            fi
        fi
    done <<< "$metrics"

    local end_time=$(date +%s%N)
    local duration=$(((end_time - start_time) / 1000000))
    [ ! -z "$DEBUG" ] && log "Injecting labels took ${duration} ms"
    
    echo "$output"
}

# Push metrics to VictoriaMetrics
push_metrics() {
    local metrics="$1"

    log "DEBUG: Full metrics to be pushed:"
    [ ! -z "$DEBUG" ] && echo "$metrics" > /tmp/metrics_full.txt

    # Print metrics to log for debugging
    log "Metrics to be pushed:"
    echo "$metrics" >&2

    local start_time=$(date +%s%N)
    RESPONSE=$(echo "$metrics" | curl -s -w "%{http_code}" -o /dev/null -X POST --data-binary @- "$VM_URL")
    local end_time=$(date +%s%N)
    local duration=$(((end_time - start_time) / 1000000))
    [ ! -z "$DEBUG" ] && log "Pushing metrics took ${duration} ms"

    if [[ "$RESPONSE" -ne 200 && "$RESPONSE" -ne 204 ]]; then
        log "Failed to push metrics to VictoriaMetrics. HTTP response code: $RESPONSE"
        exit 1
    fi
}

# Trap any errors and exit gracefully
trap 'log "An error occurred. Exiting." ; exit 1' ERR

# MAIN SCRIPT EXECUTION

validate_and_renew_token

log "Scraping metrics from $METRICS_URL..."
start_time=$(date +%s%N)
METRICS=$(curl -s -k -H "session: $AUTH_TOKEN" "$METRICS_URL")
end_time=$(date +%s%N)
duration=$(((end_time - start_time) / 1000000))
[ ! -z "$DEBUG" ] && log "Scraping metrics took ${duration} ms"

if [[ $? -ne 0 || -z "$METRICS" ]]; then
    log "Failed to scrape metrics from $METRICS_URL"
    exit 1
fi

log "Metrics scraped successfully."

log "Injecting labels into metrics..."
start_time=$(date +%s%N)
METRICS_WITH_LABELS=$(inject_labels "$METRICS" "${LABELS[@]}")
end_time=$(date +%s%N)
duration=$(((end_time - start_time) / 1000000))
[ ! -z "$DEBUG" ] && log "Injecting labels took ${duration} ms"

log "Pushing metrics to VictoriaMetrics at $VM_URL..."
start_time=$(date +%s%N)
push_metrics "$METRICS_WITH_LABELS"
end_time=$(date +%s%N)
duration=$(((end_time - start_time) / 1000000))
[ ! -z "$DEBUG" ] && log "Pushing metrics took ${duration} ms"

log "Metrics pushed successfully."
