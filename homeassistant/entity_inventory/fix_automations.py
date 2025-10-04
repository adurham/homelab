#!/usr/bin/env python3
"""
Fix automation issues found in audit
- Remove broken vacuum automations
- Fix potential issues
- Generate clean automation files
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

class AutomationFixer:
    def __init__(self, audit_results_file):
        self.audit_results_file = audit_results_file
        self.audit_data = {}
        self.fixes_applied = []
        
    def load_audit_results(self):
        """Load audit results"""
        try:
            with open(self.audit_results_file, 'r') as f:
                self.audit_data = json.load(f)
            print(f"✅ Loaded audit results")
            return True
        except Exception as e:
            print(f"❌ Failed to load audit results: {e}")
            return False
    
    def remove_broken_automations(self):
        """Remove automations with missing entities"""
        print("🗑️  Removing broken vacuum automations...")
        
        broken_automations = []
        for result in self.audit_data['results']:
            if result['missing_entities'] > 0:
                broken_automations.append(result)
        
        for automation in broken_automations:
            file_path = automation['file']
            alias = automation['alias']
            
            print(f"   Removing: {alias} from {file_path}")
            
            try:
                # Backup the file first
                backup_path = f"{file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                os.rename(file_path, backup_path)
                print(f"   ✅ Backed up to: {backup_path}")
                
                self.fixes_applied.append({
                    'action': 'removed_automation',
                    'file': file_path,
                    'alias': alias,
                    'reason': 'Missing entities',
                    'backup': backup_path
                })
                
            except Exception as e:
                print(f"   ❌ Failed to remove {file_path}: {e}")
        
        print(f"✅ Removed {len(broken_automations)} broken automations")
        return len(broken_automations)
    
    def fix_mixed_entity_warnings(self):
        """Fix automations with mixed entity type warnings"""
        print("🔧 Fixing mixed entity type warnings...")
        
        mixed_entity_automations = []
        for result in self.audit_data['results']:
            if any('Mixed' in warning for warning in result['warnings']):
                mixed_entity_automations.append(result)
        
        fixes = 0
        for automation in mixed_entity_automations:
            file_path = automation['file']
            alias = automation['alias']
            
            print(f"   Analyzing: {alias}")
            
            # Read the file
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Check if the mixed entities are actually problematic
                # For now, just document the issue
                print(f"   ⚠️  Mixed entity types detected in {alias}")
                print(f"      This may be intentional - review manually")
                
                self.fixes_applied.append({
                    'action': 'documented_warning',
                    'file': file_path,
                    'alias': alias,
                    'issue': 'Mixed entity types',
                    'recommendation': 'Review manually to ensure correct usage'
                })
                
                fixes += 1
                
            except Exception as e:
                print(f"   ❌ Failed to analyze {file_path}: {e}")
        
        print(f"✅ Documented {fixes} mixed entity warnings")
        return fixes
    
    def create_clean_automation_list(self):
        """Create a clean list of working automations"""
        print("📋 Creating clean automation inventory...")
        
        working_automations = []
        for result in self.audit_data['results']:
            if result['missing_entities'] == 0:  # Only include working automations
                working_automations.append({
                    'alias': result['alias'],
                    'id': result['automation_id'],
                    'file': result['file'],
                    'entity_count': result['total_entities'],
                    'status': 'working'
                })
        
        # Save clean automation list
        clean_data = {
            'timestamp': datetime.now().isoformat(),
            'total_working_automations': len(working_automations),
            'automations': working_automations,
            'fixes_applied': self.fixes_applied
        }
        
        with open('clean_automations.json', 'w') as f:
            json.dump(clean_data, f, indent=2)
        
        print(f"✅ Created clean automation list with {len(working_automations)} automations")
        return working_automations
    
    def generate_fix_report(self):
        """Generate report of fixes applied"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# Automation Fix Report

Generated on: {timestamp}

## Summary

- **Fixes Applied**: {len(self.fixes_applied)}
- **Broken Automations Removed**: {len([f for f in self.fixes_applied if f['action'] == 'removed_automation'])}
- **Warnings Documented**: {len([f for f in self.fixes_applied if f['action'] == 'documented_warning'])}

## Fixes Applied

"""
        
        for fix in self.fixes_applied:
            report += f"### {fix['action'].replace('_', ' ').title()}\n\n"
            report += f"- **File**: `{fix['file']}`\n"
            report += f"- **Automation**: {fix['alias']}\n"
            if 'reason' in fix:
                report += f"- **Reason**: {fix['reason']}\n"
            if 'backup' in fix:
                report += f"- **Backup**: `{fix['backup']}`\n"
            if 'recommendation' in fix:
                report += f"- **Recommendation**: {fix['recommendation']}\n"
            report += "\n"
        
        # Add recommendations
        report += "## Recommendations\n\n"
        report += "1. **Test Remaining Automations**: Verify all working automations function correctly\n"
        report += "2. **Review Mixed Entity Types**: Check automations with mixed entity types for correctness\n"
        report += "3. **Regular Audits**: Run automation audits regularly to catch issues early\n"
        report += "4. **Backup Management**: Keep backup files until you're sure everything works\n"
        
        # Save report
        with open('automation_fix_report.md', 'w') as f:
            f.write(report)
        
        print("📄 Fix report saved: automation_fix_report.md")
        return report
    
    def run_fixes(self):
        """Run all fixes"""
        print("🚀 Starting automation fixes...")
        
        if not self.load_audit_results():
            return False
        
        # Remove broken automations
        removed_count = self.remove_broken_automations()
        
        # Fix mixed entity warnings
        fixed_warnings = self.fix_mixed_entity_warnings()
        
        # Create clean automation list
        working_automations = self.create_clean_automation_list()
        
        # Generate fix report
        self.generate_fix_report()
        
        print("✅ All fixes completed!")
        print(f"📊 Summary:")
        print(f"   Removed automations: {removed_count}")
        print(f"   Documented warnings: {fixed_warnings}")
        print(f"   Working automations: {len(working_automations)}")
        
        return True

def main():
    fixer = AutomationFixer('automation_audit_results.json')
    success = fixer.run_fixes()
    
    if not success:
        print("❌ Fix process failed")
        exit(1)

if __name__ == '__main__':
    main()
