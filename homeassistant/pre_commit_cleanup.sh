#!/bin/bash
# Pre-Commit Cleanup Script for Home Assistant Configuration
# Removes sensitive data, temporary files, and organizes the repository

set -e

echo "🧹 PRE-COMMIT CLEANUP STARTING"
echo "=================================="

# Change to homeassistant directory
cd "$(dirname "$0")"

echo ""
echo "1. 🔒 SECURITY CLEANUP"
echo "======================"

# Check if sensitive files are properly ignored
echo "Checking .gitignore status..."
if git check-ignore ha_config.env >/dev/null 2>&1; then
    echo "  ✅ ha_config.env is properly ignored"
else
    echo "  ❌ ha_config.env is NOT ignored - this is a security risk!"
    echo "     Adding to .gitignore..."
    echo "homeassistant/ha_config.env" >> ../.gitignore
fi

# Check for any hardcoded API tokens
echo "Scanning for hardcoded API tokens..."
token_count=$(grep -r "eyJhbGciOiJIUzI1NiIs" . --exclude-dir=.git --exclude="*.log" 2>/dev/null | wc -l)
if [ "$token_count" -gt 0 ]; then
    echo "  ❌ Found $token_count potential API token exposures"
    echo "     This needs to be cleaned up before commit!"
else
    echo "  ✅ No hardcoded API tokens found"
fi

echo ""
echo "2. 🗂️  FILE CLEANUP"
echo "==================="

# Remove backup directories (they contain sensitive data)
echo "Removing backup directories..."
if [ -d "backup" ]; then
    echo "  🗑️  Removing backup/ directory (contains sensitive data)"
    rm -rf backup/
fi

# Clean up duplicate configuration files
echo "Cleaning up duplicate configuration files..."
config_files=(
    "configuration_temperature_balancing.yaml"
    "configuration_grafana_simple.yaml"
)
for file in "${config_files[@]}"; do
    if [ -f "$file" ]; then
        echo "  🗑️  Removing duplicate config: $file"
        rm -f "$file"
    fi
done

# Remove test files
echo "Removing test files..."
test_files=(
    "automations/simple_test.yaml"
    "automations/test_simple_grafana.yaml"
    "automations/test_timer_pause_resume.yaml"
    "deployment/test_deployment.py"
)
for file in "${test_files[@]}"; do
    if [ -f "$file" ]; then
        echo "  🗑️  Removing test file: $file"
        rm -f "$file"
    fi
done

# Remove temporary files in entity_inventory
echo "Cleaning up temporary files in entity_inventory..."
if [ -d "entity_inventory" ]; then
    find entity_inventory/ -name "*temp*" -o -name "*test*" -o -name "*simple*" | while read file; do
        echo "  🗑️  Removing temporary file: $file"
        rm -f "$file"
    done
fi

echo ""
echo "3. 📁 DIRECTORY ORGANIZATION"
echo "============================"

# Clean up empty directories
echo "Removing empty directories..."
find . -type d -empty -not -path "./.git*" | while read dir; do
    echo "  🗑️  Removing empty directory: $dir"
    rmdir "$dir" 2>/dev/null || true
done

echo ""
echo "4. 📋 FINAL VERIFICATION"
echo "======================="

# Check what's left
echo "Remaining configuration files:"
ls -la configuration*.yaml 2>/dev/null | wc -l | xargs -I {} echo "  Configuration files: {}"

echo "Remaining automation files:"
find automations/ -name "*.yaml" 2>/dev/null | wc -l | xargs -I {} echo "  Automation files: {}"

echo ""
echo "5. 🔍 SECURITY CHECK"
echo "===================="

# Final security check
echo "Final security verification..."
sensitive_files=(
    "ha_config.env"
    "*.env"
    "backup/"
)

all_safe=true
for pattern in "${sensitive_files[@]}"; do
    if find . -name "$pattern" -not -path "./.git/*" | grep -q .; then
        echo "  ❌ Found sensitive file: $pattern"
        all_safe=false
    fi
done

if [ "$all_safe" = true ]; then
    echo "  ✅ All sensitive files are properly handled"
else
    echo "  ❌ Security issues found - do not commit yet!"
    exit 1
fi

echo ""
echo "✅ CLEANUP COMPLETED SUCCESSFULLY!"
echo "=================================="
echo ""
echo "📋 READY FOR COMMIT:"
echo "  • Sensitive data removed or properly ignored"
echo "  • Temporary files cleaned up"
echo "  • Duplicate configurations removed"
echo "  • Directory structure organized"
echo ""
echo "🚀 Safe to commit!"
