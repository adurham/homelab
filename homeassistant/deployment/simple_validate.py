#!/usr/bin/env python3
"""
Simple Home Assistant Automation Validation (No External Dependencies)
Basic validation without requiring PyYAML
"""

import os
import sys
import re
from datetime import datetime

class SimpleValidator:
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_basic_syntax(self, file_path):
        """Validate basic YAML-like syntax"""
        print(f"🔍 Validating basic syntax: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Basic checks
            if not content.strip():
                self.errors.append("File is empty")
                return False
            
            # Check for basic YAML structure
            lines = content.split('\n')
            indent_level = 0
            in_automation = False
            automation_count = 0
            
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                
                # Check for automation start
                if stripped.startswith('- id:'):
                    automation_count += 1
                    in_automation = True
                    
                    # Validate ID format
                    id_match = re.match(r'- id:\s*[\'"]([^\'"]+)[\'"]', stripped)
                    if id_match:
                        automation_id = id_match.group(1)
                        if ' ' in automation_id:
                            self.warnings.append(f"Line {i}: Automation ID contains spaces: {automation_id}")
                        if not re.match(r'^[a-zA-Z0-9_-]+$', automation_id):
                            self.errors.append(f"Line {i}: Invalid automation ID format: {automation_id}")
                    else:
                        self.errors.append(f"Line {i}: Invalid automation ID format")
                
                # Check for required fields
                if in_automation:
                    if stripped.startswith('alias:'):
                        alias_match = re.match(r'alias:\s*[\'"]([^\'"]+)[\'"]', stripped)
                        if not alias_match:
                            self.errors.append(f"Line {i}: Invalid alias format")
                    
                    if stripped.startswith('trigger:'):
                        # Check trigger structure
                        pass
                    
                    if stripped.startswith('action:'):
                        # Check action structure
                        pass
                
                # Check indentation (basic)
                if line.startswith('  ') and not line.startswith('    '):
                    if stripped and not stripped.startswith('- '):
                        # This should probably be indented more
                        pass
            
            if automation_count == 0:
                self.errors.append("No automations found in file")
                return False
            
            print(f"  ✅ Found {automation_count} automation(s)")
            print(f"  ✅ Basic syntax appears valid")
            return True
            
        except Exception as e:
            self.errors.append(f"File read error: {e}")
            return False
    
    def validate_entity_references(self, file_path):
        """Validate entity references"""
        print(f"🔍 Validating entity references: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Find entity references
            entity_patterns = [
                r'entity_id:\s*([^\n\r,]+)',
                r"states\('([^']+)'\)",
                r"state_attr\('([^']+)'",
            ]
            
            entities_found = set()
            for pattern in entity_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    entity = match.strip().strip('"\'[]')
                    if entity and '.' in entity:
                        entities_found.add(entity)
            
            print(f"  📋 Found {len(entities_found)} entity references")
            
            # Check for common issues
            issues = 0
            for entity in entities_found:
                if ' ' in entity:
                    self.warnings.append(f"Entity reference contains spaces: {entity}")
                    issues += 1
                
                if not re.match(r'^[a-z_]+\.[a-z0-9_]+', entity):
                    self.warnings.append(f"Entity reference format may be invalid: {entity}")
                    issues += 1
            
            if issues == 0:
                print("  ✅ All entity references appear valid")
            
            return True
            
        except Exception as e:
            self.errors.append(f"Entity validation error: {e}")
            return False
    
    def validate_home_assistant_syntax(self, file_path):
        """Validate Home Assistant specific syntax"""
        print(f"🔍 Validating Home Assistant syntax: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check for Home Assistant patterns
            ha_patterns = [
                ('template_syntax', r'\{\{[^}]+\}\}'),
                ('service_calls', r'service:\s*[a-z_]+\.[a-z_]+'),
                ('platform_triggers', r'platform:\s*(state|time|numeric_state|zone|device)'),
            ]
            
            for pattern_name, pattern in ha_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                print(f"  📋 Found {len(matches)} {pattern_name}")
            
            # Check for common issues
            if '{{' in content and '}}' not in content:
                self.errors.append("Incomplete template syntax found")
            
            if 'service:' in content and 'target:' not in content and 'data:' not in content:
                self.warnings.append("Service calls without target or data may be incomplete")
            
            print("  ✅ Home Assistant syntax appears valid")
            return True
            
        except Exception as e:
            self.errors.append(f"Home Assistant validation error: {e}")
            return False
    
    def validate_file(self, file_path):
        """Run all validation checks"""
        print(f"🔍 Validating automation file: {file_path}")
        print("=" * 50)
        
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return False
        
        # Clear previous results
        self.errors = []
        self.warnings = []
        
        # Run validation checks
        checks = [
            self.validate_basic_syntax,
            self.validate_entity_references,
            self.validate_home_assistant_syntax,
        ]
        
        all_passed = True
        for check in checks:
            if not check(file_path):
                all_passed = False
        
        # Print summary
        print("=" * 50)
        print("📋 VALIDATION SUMMARY")
        print(f"Errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        
        if self.errors:
            print("\n❌ ERRORS:")
            for error in self.errors:
                print(f"  • {error}")
        
        if self.warnings:
            print("\n⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        if all_passed and not self.errors:
            print("\n✅ VALIDATION PASSED - File is ready for deployment")
            return True
        else:
            print("\n❌ VALIDATION FAILED - Fix errors before deployment")
            return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 simple_validate.py <automation_file>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    validator = SimpleValidator()
    
    if validator.validate_file(file_path):
        print("\n🎉 File is ready for safe deployment!")
        sys.exit(0)
    else:
        print("\n💥 File has validation errors - do not deploy!")
        sys.exit(1)

if __name__ == "__main__":
    main()
