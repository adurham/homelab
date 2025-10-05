#!/usr/bin/env python3
"""
Home Assistant Automation Validation System
Validates automation syntax and configuration before deployment
"""

import os
import sys
import yaml
import tempfile
import shutil
import subprocess
from datetime import datetime

class AutomationValidator:
    def __init__(self):
        self.validation_errors = []
        self.validation_warnings = []
    
    def validate_yaml_syntax(self, file_path):
        """Validate basic YAML syntax"""
        print(f"🔍 Validating YAML syntax: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                yaml.safe_load(f)
            print("  ✅ YAML syntax is valid")
            return True
        except yaml.YAMLError as e:
            error_msg = f"YAML syntax error: {e}"
            print(f"  ❌ {error_msg}")
            self.validation_errors.append(error_msg)
            return False
        except Exception as e:
            error_msg = f"File read error: {e}"
            print(f"  ❌ {error_msg}")
            self.validation_errors.append(error_msg)
            return False
    
    def validate_automation_structure(self, file_path):
        """Validate automation structure and required fields"""
        print(f"🔍 Validating automation structure: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = yaml.safe_load(f)
            
            if not isinstance(content, list):
                error_msg = "Automation file must contain a list of automations"
                print(f"  ❌ {error_msg}")
                self.validation_errors.append(error_msg)
                return False
            
            for i, automation in enumerate(content):
                if not isinstance(automation, dict):
                    error_msg = f"Automation {i+1} must be a dictionary"
                    print(f"  ❌ {error_msg}")
                    self.validation_errors.append(error_msg)
                    continue
                
                # Check required fields
                required_fields = ['id', 'alias', 'trigger']
                for field in required_fields:
                    if field not in automation:
                        error_msg = f"Automation {i+1} missing required field: {field}"
                        print(f"  ❌ {error_msg}")
                        self.validation_errors.append(error_msg)
                
                # Validate ID format
                if 'id' in automation:
                    automation_id = automation['id']
                    if not isinstance(automation_id, str) or not automation_id.strip():
                        error_msg = f"Automation {i+1} has invalid ID: {automation_id}"
                        print(f"  ❌ {error_msg}")
                        self.validation_errors.append(error_msg)
                    elif ' ' in automation_id:
                        warning_msg = f"Automation {i+1} ID contains spaces: {automation_id}"
                        print(f"  ⚠️  {warning_msg}")
                        self.validation_warnings.append(warning_msg)
                
                # Validate alias
                if 'alias' in automation:
                    alias = automation['alias']
                    if not isinstance(alias, str) or not alias.strip():
                        error_msg = f"Automation {i+1} has invalid alias: {alias}"
                        print(f"  ❌ {error_msg}")
                        self.validation_errors.append(error_msg)
                
                # Validate trigger structure
                if 'trigger' in automation:
                    trigger = automation['trigger']
                    if not isinstance(trigger, list):
                        error_msg = f"Automation {i+1} trigger must be a list"
                        print(f"  ❌ {error_msg}")
                        self.validation_errors.append(error_msg)
                    else:
                        for j, trigger_item in enumerate(trigger):
                            if not isinstance(trigger_item, dict):
                                error_msg = f"Automation {i+1}, trigger {j+1} must be a dictionary"
                                print(f"  ❌ {error_msg}")
                                self.validation_errors.append(error_msg)
                            elif 'platform' not in trigger_item:
                                error_msg = f"Automation {i+1}, trigger {j+1} missing platform"
                                print(f"  ❌ {error_msg}")
                                self.validation_errors.append(error_msg)
                
                # Validate action structure
                if 'action' in automation:
                    action = automation['action']
                    if not isinstance(action, list):
                        error_msg = f"Automation {i+1} action must be a list"
                        print(f"  ❌ {error_msg}")
                        self.validation_errors.append(error_msg)
                    else:
                        for j, action_item in enumerate(action):
                            if not isinstance(action_item, dict):
                                error_msg = f"Automation {i+1}, action {j+1} must be a dictionary"
                                print(f"  ❌ {error_msg}")
                                self.validation_errors.append(error_msg)
                            elif 'service' not in action_item and 'scene' not in action_item and 'device_id' not in action_item:
                                # Check for other valid action types
                                valid_actions = ['delay', 'wait_template', 'choose', 'repeat', 'parallel', 'sequence', 'if', 'while']
                                if not any(key in action_item for key in valid_actions):
                                    warning_msg = f"Automation {i+1}, action {j+1} may be invalid (no service/scene/device_id)"
                                    print(f"  ⚠️  {warning_msg}")
                                    self.validation_warnings.append(warning_msg)
            
            if not self.validation_errors:
                print(f"  ✅ Found {len(content)} automations with valid structure")
                return True
            else:
                print(f"  ❌ Found {len(self.validation_errors)} structure errors")
                return False
                
        except Exception as e:
            error_msg = f"Structure validation error: {e}"
            print(f"  ❌ {error_msg}")
            self.validation_errors.append(error_msg)
            return False
    
    def validate_entity_references(self, file_path):
        """Validate that entity references are properly formatted"""
        print(f"🔍 Validating entity references: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Look for common entity reference patterns
            import re
            
            # Find entity references in the file
            entity_patterns = [
                r'entity_id:\s*([^\n\r,]+)',
                r'entities:\s*([^\n\r,]+)',
                r'entity:\s*([^\n\r,]+)',
                r"states\('([^']+)'\)",
                r"state_attr\('([^']+)'",
            ]
            
            entities_found = set()
            for pattern in entity_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    # Clean up the match
                    entity = match.strip().strip('"\'[]')
                    if entity and '.' in entity:
                        entities_found.add(entity)
            
            print(f"  📋 Found {len(entities_found)} entity references")
            
            # Check for common issues
            issues_found = 0
            
            for entity in entities_found:
                # Check for spaces in entity names
                if ' ' in entity:
                    warning_msg = f"Entity reference contains spaces: {entity}"
                    print(f"  ⚠️  {warning_msg}")
                    self.validation_warnings.append(warning_msg)
                    issues_found += 1
                
                # Check for common entity patterns
                if not re.match(r'^[a-z_]+\.[a-z0-9_]+', entity):
                    warning_msg = f"Entity reference format may be invalid: {entity}"
                    print(f"  ⚠️  {warning_msg}")
                    self.validation_warnings.append(warning_msg)
                    issues_found += 1
            
            if issues_found == 0:
                print("  ✅ All entity references appear valid")
            
            return True
            
        except Exception as e:
            error_msg = f"Entity validation error: {e}"
            print(f"  ❌ {error_msg}")
            self.validation_errors.append(error_msg)
            return False
    
    def validate_home_assistant_compatibility(self, file_path):
        """Validate Home Assistant specific syntax"""
        print(f"🔍 Validating Home Assistant compatibility: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check for Home Assistant specific patterns
            ha_patterns = [
                ('template_syntax', r'\{\{[^}]+\}\}'),
                ('service_calls', r'service:\s*[a-z_]+\.[a-z_]+'),
                ('platform_triggers', r'platform:\s*(state|time|numeric_state|zone|device)'),
            ]
            
            for pattern_name, pattern in ha_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                print(f"  📋 Found {len(matches)} {pattern_name}")
            
            # Check for common Home Assistant issues
            issues = []
            
            # Check for invalid template syntax
            if '{{' in content and '}}' not in content:
                issues.append("Incomplete template syntax found")
            
            # Check for service calls without proper formatting
            if 'service:' in content and 'target:' not in content and 'data:' not in content:
                warning_msg = "Service calls without target or data may be incomplete"
                print(f"  ⚠️  {warning_msg}")
                self.validation_warnings.append(warning_msg)
            
            if not issues:
                print("  ✅ Home Assistant compatibility appears good")
                return True
            else:
                for issue in issues:
                    print(f"  ❌ {issue}")
                    self.validation_errors.append(issue)
                return False
                
        except Exception as e:
            error_msg = f"Home Assistant validation error: {e}"
            print(f"  ❌ {error_msg}")
            self.validation_errors.append(error_msg)
            return False
    
    def validate_file(self, file_path):
        """Run all validation checks on a file"""
        print(f"🔍 Validating automation file: {file_path}")
        print("=" * 50)
        
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return False
        
        # Clear previous validation results
        self.validation_errors = []
        self.validation_warnings = []
        
        # Run all validation checks
        checks = [
            self.validate_yaml_syntax,
            self.validate_automation_structure,
            self.validate_entity_references,
            self.validate_home_assistant_compatibility,
        ]
        
        all_passed = True
        for check in checks:
            if not check(file_path):
                all_passed = False
        
        # Print summary
        print("=" * 50)
        print("📋 VALIDATION SUMMARY")
        print(f"Errors: {len(self.validation_errors)}")
        print(f"Warnings: {len(self.validation_warnings)}")
        
        if self.validation_errors:
            print("\n❌ ERRORS:")
            for error in self.validation_errors:
                print(f"  • {error}")
        
        if self.validation_warnings:
            print("\n⚠️  WARNINGS:")
            for warning in self.validation_warnings:
                print(f"  • {warning}")
        
        if all_passed and not self.validation_errors:
            print("\n✅ VALIDATION PASSED - File is ready for deployment")
            return True
        else:
            print("\n❌ VALIDATION FAILED - Fix errors before deployment")
            return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 validate_automations.py <automation_file>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    validator = AutomationValidator()
    
    if validator.validate_file(file_path):
        print("\n🎉 File is ready for safe deployment!")
        sys.exit(0)
    else:
        print("\n💥 File has validation errors - do not deploy!")
        sys.exit(1)

if __name__ == "__main__":
    main()
