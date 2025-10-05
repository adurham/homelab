#!/bin/bash
# Setup Grafana Logging for Home Assistant Automations
# This script sets up comprehensive logging to Grafana for all automations

set -e

echo "🔧 Setting up Grafana logging for Home Assistant automations..."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Step 1: Backup current configuration
log_info "Creating backup of current configuration..."
cp ../configuration_merged.yaml ../backup/configuration_before_grafana_$(date +%Y%m%d_%H%M%S).yaml
log_success "Backup created"

# Step 2: Merge Grafana logging configuration
log_info "Merging Grafana logging configuration..."
cat ../configuration_grafana_logging.yaml >> ../configuration_merged.yaml
log_success "Grafana logging configuration merged"

# Step 3: Deploy enhanced automations with Grafana logging
log_info "Deploying enhanced automations with Grafana logging..."

# Copy enhanced automations
cp ../entity_inventory/temperature_balancing_with_grafana.yaml ../automations/temperature_balancing_grafana.yaml
cp ../entity_inventory/hot_water_with_grafana.yaml ../automations/hot_water_circulation_grafana.yaml
cp ../entity_inventory/garage_lights_with_grafana.yaml ../automations/garage_lights_grafana.yaml

log_success "Enhanced automations deployed"

# Step 4: Deploy configuration and restart
log_info "Deploying configuration and restarting Home Assistant..."
./minimal_deploy.sh --restart

# Step 5: Wait for restart
log_info "Waiting for Home Assistant to restart..."
sleep 30

# Step 6: Verify deployment
log_info "Verifying deployment..."
if curl -s http://192.168.86.2:8123/api/ >/dev/null; then
    log_success "Home Assistant is back online"
else
    log_warning "Home Assistant may still be restarting"
fi

# Step 7: Provide Grafana dashboard setup instructions
echo ""
log_success "Grafana logging setup completed!"
echo ""
log_info "Next steps to complete Grafana setup:"
echo "1. Open Grafana at http://192.168.86.2:3000"
echo "2. Import the dashboard from ../grafana_dashboard.json"
echo "3. Configure InfluxDB data source if not already done"
echo "4. Verify sensors are being logged in Grafana"
echo ""
log_info "New sensors available for Grafana:"
echo "  • input_number.occupied_rooms_count"
echo "  • input_number.temperature_variance_occupied"
echo "  • input_number.hot_water_pump_runtime"
echo "  • input_number.hot_water_pump_cycles_today"
echo "  • input_number.garage_lights_on_time"
echo "  • input_number.garage_door_opens_today"
echo "  • sensor.temperature_efficiency_score"
echo "  • sensor.hot_water_efficiency_score"
echo "  • sensor.garage_lights_efficiency_score"
echo ""
log_info "Enhanced automations deployed:"
echo "  • automation.temperature_balancing_with_grafana"
echo "  • automation.hot_water_circulation_with_grafana"
echo "  • automation.garage_lights_with_grafana"
echo ""
log_success "Setup complete! Check Grafana for automation performance metrics."
