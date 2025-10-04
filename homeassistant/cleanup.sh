#!/bin/bash
# Home Assistant Directory Cleanup Script
# Removes temporary files, backups, and ensures no sensitive data is committed

set -e

echo "🧹 Starting Home Assistant directory cleanup..."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
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

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 1. Remove backup files
log_info "Removing backup files..."
backup_count=0
for file in $(find . -name "*.backup*" -type f); do
    rm -f "$file"
    backup_count=$((backup_count + 1))
done
log_success "Removed $backup_count backup files"

# 2. Remove temporary files
log_info "Removing temporary files..."
temp_count=0
for file in $(find . -name "*.tmp" -o -name "*.temp" -o -name "*.cache" -type f); do
    rm -f "$file"
    temp_count=$((temp_count + 1))
done
log_success "Removed $temp_count temporary files"

# 3. Remove log files
log_info "Removing log files..."
log_count=0
for file in $(find . -name "*.log" -type f); do
    rm -f "$file"
    log_count=$((log_count + 1))
done
log_success "Removed $log_count log files"

# 4. Remove Python cache files
log_info "Removing Python cache files..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -type f -delete 2>/dev/null || true
find . -name "*.pyo" -type f -delete 2>/dev/null || true
log_success "Removed Python cache files"

# 5. Check for sensitive files
log_info "Checking for sensitive files..."
sensitive_files=()
for file in $(find . -type f \( -name "*.env" -o -name "*.key" -o -name "*.pem" -o -name "*password*" -o -name "*secret*" -o -name "*token*" \)); do
    if [[ "$file" != "./ha_config.env" ]]; then  # Skip the legitimate config file
        sensitive_files+=("$file")
    fi
done

if [ ${#sensitive_files[@]} -gt 0 ]; then
    log_warning "Found potentially sensitive files:"
    for file in "${sensitive_files[@]}"; do
        echo "  - $file"
    done
    log_warning "Please review these files before committing"
else
    log_success "No sensitive files found"
fi

# 6. Remove generated files that shouldn't be committed
log_info "Removing generated files..."
generated_files=(
    "entity_inventory/entity_inventory.json"
    "entity_inventory/entity_inventory.md"
    "entity_inventory/automation_audit_results.json"
    "entity_inventory/automation_audit_report.md"
    "entity_inventory/automation_fix_report.md"
    "entity_inventory/clean_automations.json"
)

for file in "${generated_files[@]}"; do
    if [ -f "$file" ]; then
        rm -f "$file"
        log_success "Removed generated file: $file"
    fi
done

# 7. Clean up duplicate/unused files
log_info "Cleaning up duplicate files..."

# Remove old automation files that have been replaced
old_files=(
    "entity_inventory/garage_lights_optimal.yaml"
    "entity_inventory/garage_lights_enhanced.yaml"
    "entity_inventory/garage_lights_advanced.yaml"
    "entity_inventory/garage_lights_simple.yaml"
    "entity_inventory/improved_garage_lights.yaml"
    "entity_inventory/improved_garage_lights_simple.yaml"
)

for file in "${old_files[@]}"; do
    if [ -f "$file" ]; then
        rm -f "$file"
        log_success "Removed old file: $file"
    fi
done

# 8. Update .gitignore if needed
log_info "Checking .gitignore..."
if ! grep -q "automation_audit" ../.gitignore; then
    echo "" >> ../.gitignore
    echo "# Automation audit files" >> ../.gitignore
    echo "homeassistant/entity_inventory/automation_audit_*" >> ../.gitignore
    echo "homeassistant/entity_inventory/clean_automations.json" >> ../.gitignore
    log_success "Updated .gitignore with audit files"
fi

# 9. Create a clean README for the entity_inventory directory
log_info "Creating clean entity_inventory README..."
cat > entity_inventory/README.md << 'EOF'
# Home Assistant Entity Inventory

This directory contains tools for managing and auditing Home Assistant entities and automations.

## Files

- `extract_with_config.py` - Extract entities using API token from ha_config.env
- `simple_audit.py` - Audit automations against entity inventory
- `fix_automations.py` - Fix automation issues found in audit

## Usage

1. Ensure `ha_config.env` contains your Home Assistant API token
2. Run `python3 extract_with_config.py` to extract entities
3. Run `python3 simple_audit.py` to audit automations
4. Run `python3 fix_automations.py` to fix issues

## Generated Files

The following files are generated and should not be committed:
- `entity_inventory.json` - Entity inventory data
- `entity_inventory.md` - Human-readable entity documentation
- `automation_audit_*` - Audit reports and results
- `clean_automations.json` - Clean automation list

These files are automatically ignored by git.
EOF

log_success "Created clean entity_inventory README"

# 10. Final summary
echo ""
log_success "Cleanup completed successfully!"
echo ""
log_info "Summary of actions:"
echo "  - Removed backup files: $backup_count"
echo "  - Removed temporary files: $temp_count"
echo "  - Removed log files: $log_count"
echo "  - Cleaned Python cache files"
echo "  - Removed generated files"
echo "  - Removed old/duplicate files"
echo "  - Updated .gitignore"
echo "  - Created clean documentation"
echo ""
log_info "The directory is now ready for commit!"
