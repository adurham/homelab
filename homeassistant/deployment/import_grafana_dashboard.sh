#!/bin/bash
# Simple Grafana Dashboard Import Script
# Imports the Home Assistant automation dashboard using curl

set -e

# Configuration
GRAFANA_URL="${GRAFANA_URL:-http://192.168.86.2:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
DASHBOARD_FILE="../grafana_dashboard.json"

echo "🚀 GRAFANA DASHBOARD IMPORT"
echo "=================================="

# Check if dashboard file exists
if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "❌ Dashboard file not found: $DASHBOARD_FILE"
    echo "   Please ensure grafana_dashboard.json exists in the homeassistant directory"
    exit 1
fi

echo "📄 Dashboard file found: $DASHBOARD_FILE"

# Test Grafana connection
echo "🔍 Testing Grafana connection..."
if curl -s -o /dev/null -w "%{http_code}" "$GRAFANA_URL/api/health" | grep -q "200"; then
    echo "✅ Grafana is accessible at $GRAFANA_URL"
else
    echo "❌ Cannot connect to Grafana at $GRAFANA_URL"
    echo ""
    echo "Please check:"
    echo "  1. Grafana is installed and running"
    echo "  2. Grafana is accessible at the configured URL"
    echo "  3. Network connectivity is working"
    echo ""
    echo "Common Grafana URLs:"
    echo "  - http://192.168.86.2:3000 (standard port)"
    echo "  - http://192.168.86.2:8123/grafana (Home Assistant addon)"
    echo "  - http://homeassistant.local:3000"
    exit 1
fi

# Get API key
echo "🔐 Getting Grafana API key..."
API_KEY=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"homeassistant-import-$(date +%s)\", \"role\": \"Admin\"}" \
  -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
  "$GRAFANA_URL/api/auth/keys" | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['key'])" 2>/dev/null)

if [ -z "$API_KEY" ]; then
    echo "❌ Failed to get API key. Please check credentials."
    echo "   Default credentials: admin/admin"
    echo "   Set GRAFANA_USER and GRAFANA_PASSWORD environment variables if different"
    exit 1
fi

echo "✅ API key obtained"

# Prepare dashboard data
echo "📊 Preparing dashboard for import..."
TEMP_DASHBOARD=$(mktemp)
cat "$DASHBOARD_FILE" | \
python3 -c "
import sys, json
data = json.load(sys.stdin)
data['overwrite'] = True
data['folderId'] = 0
print(json.dumps(data))
" > "$TEMP_DASHBOARD"

# Import dashboard
echo "📤 Importing dashboard..."
RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/grafana_response.json \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d @"$TEMP_DASHBOARD" \
  "$GRAFANA_URL/api/dashboards/db")

HTTP_CODE="${RESPONSE: -3}"

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Dashboard imported successfully!"
    
    # Get dashboard URL
    DASHBOARD_URL=$(python3 -c "
import sys, json
try:
    with open('/tmp/grafana_response.json', 'r') as f:
        data = json.load(f)
    print('$GRAFANA_URL' + data.get('url', '/dashboard/home'))
except:
    print('$GRAFANA_URL/dashboard/home')
" 2>/dev/null)
    
    echo ""
    echo "🎉 DASHBOARD IMPORT COMPLETED!"
    echo "================================"
    echo "📊 Dashboard URL: $DASHBOARD_URL"
    echo "🌐 Grafana URL: $GRAFANA_URL"
    echo ""
    echo "📋 Next steps:"
    echo "  1. Open Grafana and verify the dashboard"
    echo "  2. Check that InfluxDB datasource is configured"
    echo "  3. Verify data is flowing from Home Assistant"
    echo "  4. Customize the dashboard as needed"
    
    # Clean up
    rm -f "$TEMP_DASHBOARD" "/tmp/grafana_response.json"
    
else
    echo "❌ Dashboard import failed (HTTP $HTTP_CODE)"
    echo "Response:"
    cat /tmp/grafana_response.json 2>/dev/null || echo "No response details available"
    
    # Clean up
    rm -f "$TEMP_DASHBOARD" "/tmp/grafana_response.json"
    exit 1
fi
