#!/bin/bash
# Complete Grafana Integration Setup Script
# Sets up Grafana dashboard, datasource, and Home Assistant integration

set -e

echo "🚀 GRAFANA INTEGRATION SETUP"
echo "============================="

# Configuration
GRAFANA_URL="${GRAFANA_URL:-http://192.168.86.2:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
HA_URL="${HA_URL:-http://192.168.86.2:8123}"

echo "Configuration:"
echo "  Grafana URL: $GRAFANA_URL"
echo "  Home Assistant URL: $HA_URL"
echo ""

# Step 1: Check Grafana connectivity
echo "🔍 Step 1: Checking Grafana connectivity..."
if curl -s -o /dev/null -w "%{http_code}" "$GRAFANA_URL/api/health" | grep -q "200"; then
    echo "✅ Grafana is accessible"
else
    echo "❌ Grafana is not accessible"
    echo ""
    echo "Please ensure Grafana is installed and running:"
    echo "  1. Install Grafana addon in Home Assistant"
    echo "  2. Start the addon"
    echo "  3. Check the addon logs for any issues"
    echo "  4. Verify the URL is correct"
    echo ""
    echo "Common URLs:"
    echo "  - http://192.168.86.2:3000 (standard port)"
    echo "  - http://192.168.86.2:8123/grafana (Home Assistant addon)"
    exit 1
fi

# Step 2: Check Home Assistant connectivity
echo "🔍 Step 2: Checking Home Assistant connectivity..."
if curl -s -o /dev/null -w "%{http_code}" "$HA_URL/api/" | grep -q "200"; then
    echo "✅ Home Assistant is accessible"
else
    echo "❌ Home Assistant is not accessible"
    echo "   Please check the Home Assistant URL"
    exit 1
fi

# Step 3: Check InfluxDB addon
echo "🔍 Step 3: Checking InfluxDB addon..."
if curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/hassio/addons" 2>/dev/null | \
   python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'data' in data:
        addons = data['data']['addons']
        influxdb_addons = [addon for addon in addons if 'influxdb' in addon['slug'].lower()]
        if influxdb_addons:
            for addon in influxdb_addons:
                print(f'Found InfluxDB addon: {addon[\"name\"]} - State: {addon[\"state\"]}')
                if addon['state'] == 'started':
                    print('✅ InfluxDB is running')
                else:
                    print('⚠️  InfluxDB is not running')
        else:
            print('❌ InfluxDB addon not found')
except:
    print('❌ Could not check InfluxDB status')
"; then
    echo "InfluxDB check completed"
else
    echo "⚠️  Could not verify InfluxDB status"
    echo "   Please ensure InfluxDB addon is installed and running"
fi

# Step 4: Import dashboard
echo "🔍 Step 4: Importing Grafana dashboard..."
if [ -f "import_grafana_dashboard.sh" ]; then
    chmod +x import_grafana_dashboard.sh
    ./import_grafana_dashboard.sh
else
    echo "❌ Dashboard import script not found"
    echo "   Please ensure import_grafana_dashboard.sh exists"
    exit 1
fi

# Step 5: Verify Home Assistant logging configuration
echo "🔍 Step 5: Checking Home Assistant logging configuration..."
if [ -f "../configuration_grafana_logging.yaml" ]; then
    echo "✅ Grafana logging configuration found"
    echo "   Make sure to merge this with your main configuration.yaml"
    echo "   Or add the input_number and sensor definitions manually"
else
    echo "⚠️  Grafana logging configuration not found"
    echo "   The dashboard may not have data to display"
fi

echo ""
echo "🎉 GRAFANA INTEGRATION SETUP COMPLETED!"
echo "======================================="
echo ""
echo "📊 What was set up:"
echo "  ✅ Grafana connectivity verified"
echo "  ✅ Home Assistant connectivity verified"
echo "  ✅ Dashboard imported (if successful)"
echo ""
echo "📋 Next steps:"
echo "  1. Open Grafana: $GRAFANA_URL"
echo "  2. Login with credentials: $GRAFANA_USER / [password]"
echo "  3. Check the 'Home Assistant Automation Performance' dashboard"
echo "  4. Verify InfluxDB datasource is configured"
echo "  5. Check that data is flowing from Home Assistant"
echo ""
echo "🔧 If you need to configure InfluxDB datasource manually:"
echo "  1. Go to Grafana → Configuration → Data Sources"
echo "  2. Add InfluxDB datasource"
echo "  3. URL: http://a0d7b954-influxdb:8086"
echo "  4. Database: homeassistant"
echo "  5. Save & Test"
echo ""
echo "📈 Your automation metrics should now be visible in Grafana!"
