#!/usr/bin/env python3
"""
Simple automation audit using only built-in modules
"""

import json
import re
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime

class SimpleAutomationAuditor:
    def __init__(self, entity_inventory_file, automations_dir):
        self.entity_inventory_file = entity_inventory_file
        self.automations_dir = automations_dir
        self.entities = {}
        self.automations = []
        self.issues = []
        self.stats = {
            'total_automations': 0,
            'valid_automations': 0,
            'broken_references': 0,
            'missing_entities': 0,
            'warnings': 0
        }
    
    def load_entity_inventory(self):
        """Load entity inventory from JSON file"""
        try:
            with open(self.entity_inventory_file, 'r') as f:
                data = json.load(f)
                self.entities = {entity['entity_id']: entity for entity in data['entities']}
                print(f"✅ Loaded {len(self.entities)} entities from inventory")
                return True
        except Exception as e:
            print(f"❌ Failed to load entity inventory: {e}")
            return False
    
    def extract_entity_references_from_yaml(self, yaml_content):
        """Extract entity references from YAML content using regex"""
        entity_refs = set()
        
        # Pattern to match entity_id: "entity.name" or entity_id: entity.name
        entity_pattern = r'entity_id:\s*["\']?([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)["\']?'
        matches = re.findall(entity_pattern, yaml_content)
        entity_refs.update(matches)
        
        # Pattern to match entity_id: [list, of, entities]
        list_pattern = r'entity_id:\s*\[(.*?)\]'
        list_matches = re.findall(list_pattern, yaml_content, re.DOTALL)
        for match in list_matches:
            # Extract individual entities from the list
            items = re.findall(r'["\']?([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)["\']?', match)
            entity_refs.update(items)
        
        # Pattern to match direct entity references in actions
        action_pattern = r'["\']([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)["\']'
        action_matches = re.findall(action_pattern, yaml_content)
        entity_refs.update(action_matches)
        
        return entity_refs
    
    def load_automations(self):
        """Load all automation files"""
        automation_files = []
        
        # Load from individual automations directory
        individual_dir = Path(self.automations_dir) / "individual_automations"
        if individual_dir.exists():
            for yaml_file in individual_dir.rglob("*.yaml"):
                automation_files.append(yaml_file)
        
        # Load from webui automations
        webui_dir = Path(self.automations_dir) / "webui_automations"
        if webui_dir.exists():
            for yaml_file in webui_dir.rglob("*.yaml"):
                if yaml_file.name != "automations.yaml":  # Skip the combined file
                    automation_files.append(yaml_file)
        
        # Load from main automations directory
        main_automations_dir = Path(self.automations_dir) / "automations"
        if main_automations_dir.exists():
            for yaml_file in main_automations_dir.rglob("*.yaml"):
                automation_files.append(yaml_file)
        
        print(f"📁 Found {len(automation_files)} automation files")
        
        for file_path in automation_files:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Extract automation info from YAML content
                alias_match = re.search(r'alias:\s*["\']?([^"\'\n]+)["\']?', content)
                id_match = re.search(r'id:\s*["\']?([^"\'\n]+)["\']?', content)
                
                automation = {
                    'alias': alias_match.group(1).strip() if alias_match else 'Unknown',
                    'id': id_match.group(1).strip() if id_match else 'unknown',
                    'file': str(file_path),
                    'content': content
                }
                
                self.automations.append(automation)
                        
            except Exception as e:
                print(f"⚠️  Failed to parse {file_path}: {e}")
                self.issues.append({
                    'type': 'parse_error',
                    'file': str(file_path),
                    'message': str(e)
                })
        
        self.stats['total_automations'] = len(self.automations)
        print(f"✅ Loaded {len(self.automations)} automations")
        return True
    
    def audit_automation(self, automation):
        """Audit a single automation"""
        automation_id = automation.get('id', 'unknown')
        alias = automation.get('alias', 'Unknown')
        source_file = automation.get('file', 'unknown')
        content = automation.get('content', '')
        
        # Extract entity references
        entity_refs = self.extract_entity_references_from_yaml(content)
        
        # Check each entity reference
        missing_entities = []
        valid_entities = []
        
        for entity_id in entity_refs:
            if entity_id in self.entities:
                valid_entities.append(entity_id)
            else:
                missing_entities.append(entity_id)
                self.stats['missing_entities'] += 1
        
        # Check for common issues
        warnings = []
        
        # Check for hardcoded entity IDs that might be outdated
        if missing_entities:
            self.stats['broken_references'] += 1
            self.issues.append({
                'type': 'missing_entities',
                'automation_id': automation_id,
                'alias': alias,
                'file': source_file,
                'missing_entities': missing_entities,
                'severity': 'error'
            })
        
        # Check for potential issues
        if len(entity_refs) == 0:
            warnings.append("No entity references found")
        
        if len(missing_entities) > 0:
            warnings.append(f"{len(missing_entities)} missing entities")
        
        # Check for common patterns that might indicate issues
        if 'switch.' in content and 'light.' in content:
            warnings.append("Mixed switch and light entities - verify correct usage")
        
        if 'binary_sensor.' in content and 'sensor.' in content:
            warnings.append("Mixed binary_sensor and sensor entities - verify correct usage")
        
        if warnings:
            self.stats['warnings'] += 1
            self.issues.append({
                'type': 'warnings',
                'automation_id': automation_id,
                'alias': alias,
                'file': source_file,
                'warnings': warnings,
                'severity': 'warning'
            })
        
        if len(missing_entities) == 0:
            self.stats['valid_automations'] += 1
        
        return {
            'automation_id': automation_id,
            'alias': alias,
            'file': source_file,
            'total_entities': len(entity_refs),
            'valid_entities': len(valid_entities),
            'missing_entities': len(missing_entities),
            'entity_refs': list(entity_refs),
            'valid_refs': valid_entities,
            'missing_refs': missing_entities,
            'warnings': warnings
        }
    
    def audit_all(self):
        """Audit all automations"""
        print("🔍 Auditing automations against entity inventory...")
        
        results = []
        for automation in self.automations:
            result = self.audit_automation(automation)
            results.append(result)
        
        return results
    
    def generate_report(self, results):
        """Generate comprehensive audit report"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# Home Assistant Automation Audit Report

Generated on: {timestamp}

## Summary

- **Total Automations**: {self.stats['total_automations']}
- **Valid Automations**: {self.stats['valid_automations']}
- **Broken References**: {self.stats['broken_references']}
- **Missing Entities**: {self.stats['missing_entities']}
- **Warnings**: {self.stats['warnings']}

## Issues Found

"""
        
        # Group issues by type
        issues_by_type = defaultdict(list)
        for issue in self.issues:
            issues_by_type[issue['type']].append(issue)
        
        # Missing entities
        if 'missing_entities' in issues_by_type:
            report += "### Missing Entities (Errors)\n\n"
            for issue in issues_by_type['missing_entities']:
                report += f"**{issue['alias']}** (`{issue['automation_id']}`)\n"
                report += f"- File: `{issue['file']}`\n"
                report += f"- Missing entities: {', '.join(issue['missing_entities'])}\n\n"
        
        # Warnings
        if 'warnings' in issues_by_type:
            report += "### Warnings\n\n"
            for issue in issues_by_type['warnings']:
                report += f"**{issue['alias']}** (`{issue['automation_id']}`)\n"
                report += f"- File: `{issue['file']}`\n"
                report += f"- Warnings: {', '.join(issue['warnings'])}\n\n"
        
        # Parse errors
        if 'parse_error' in issues_by_type:
            report += "### Parse Errors\n\n"
            for issue in issues_by_type['parse_error']:
                report += f"**File**: `{issue['file']}`\n"
                report += f"**Error**: {issue['message']}\n\n"
        
        # Detailed results
        report += "## Detailed Results\n\n"
        
        for result in results:
            report += f"### {result['alias']} (`{result['automation_id']}`)\n"
            report += f"- **File**: `{result['file']}`\n"
            report += f"- **Total Entity References**: {result['total_entities']}\n"
            report += f"- **Valid Entities**: {result['valid_entities']}\n"
            report += f"- **Missing Entities**: {result['missing_entities']}\n"
            
            if result['valid_refs']:
                report += f"- **Valid References**: {', '.join(result['valid_refs'][:5])}"
                if len(result['valid_refs']) > 5:
                    report += f" (and {len(result['valid_refs']) - 5} more)"
                report += "\n"
            
            if result['missing_refs']:
                report += f"- **Missing References**: {', '.join(result['missing_refs'])}\n"
            
            if result['warnings']:
                report += f"- **Warnings**: {', '.join(result['warnings'])}\n"
            
            report += "\n"
        
        # Recommendations
        report += "## Recommendations\n\n"
        
        if self.stats['missing_entities'] > 0:
            report += "1. **Fix Missing Entities**: Update automations to use correct entity IDs\n"
            report += "2. **Check Entity Names**: Verify entity names haven't changed\n"
            report += "3. **Update References**: Use the entity inventory to find correct entity IDs\n\n"
        
        if self.stats['warnings'] > 0:
            report += "4. **Review Warnings**: Address automation logic issues\n"
            report += "5. **Test Automations**: Verify automations work as expected\n\n"
        
        report += "6. **Regular Audits**: Run this audit regularly to catch issues early\n"
        report += "7. **Entity Management**: Keep entity inventory updated when adding/removing devices\n"
        
        return report
    
    def run_audit(self):
        """Run complete audit process"""
        print("🚀 Starting automation audit...")
        
        # Load data
        if not self.load_entity_inventory():
            return False
        
        if not self.load_automations():
            return False
        
        # Run audit
        results = self.audit_all()
        
        # Generate report
        report = self.generate_report(results)
        
        # Save report
        with open('automation_audit_report.md', 'w') as f:
            f.write(report)
        
        # Save JSON results
        audit_data = {
            'timestamp': datetime.now().isoformat(),
            'stats': self.stats,
            'issues': self.issues,
            'results': results
        }
        
        with open('automation_audit_results.json', 'w') as f:
            json.dump(audit_data, f, indent=2, default=str)
        
        print("✅ Audit completed successfully!")
        print("📄 Report: automation_audit_report.md")
        print("📊 Data: automation_audit_results.json")
        
        # Print summary
        print(f"\n📊 Audit Summary:")
        print(f"   Total automations: {self.stats['total_automations']}")
        print(f"   Valid automations: {self.stats['valid_automations']}")
        print(f"   Broken references: {self.stats['broken_references']}")
        print(f"   Missing entities: {self.stats['missing_entities']}")
        print(f"   Warnings: {self.stats['warnings']}")
        
        return True

def main():
    auditor = SimpleAutomationAuditor('entity_inventory.json', '..')
    success = auditor.run_audit()
    
    if not success:
        print("❌ Audit failed")
        exit(1)

if __name__ == '__main__':
    main()
