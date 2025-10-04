#!/usr/bin/env python3
"""
Test script to verify Home Assistant deployment
Tests connectivity, file presence, and automation functionality
"""

import requests
import json
import sys
from typing import Dict, List

class HATester:
    def __init__(self, ha_url: str, token: str = None):
        self.ha_url = ha_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        
        if self.token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json'
            })
    
    def test_connectivity(self) -> bool:
        """Test basic connectivity to Home Assistant"""
        try:
            response = self.session.get(f'{self.ha_url}/api/')
            if response.status_code == 200:
                print("✅ Home Assistant API is accessible")
                return True
            else:
                print(f"❌ Home Assistant API returned status {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Cannot connect to Home Assistant: {e}")
            return False
    
    def test_automations(self) -> bool:
        """Test if automations are loaded"""
        try:
            response = self.session.get(f'{self.ha_url}/api/states')
            if response.status_code == 200:
                states = response.json()
                automation_states = [s for s in states if s['entity_id'].startswith('automation.')]
                
                # Look for our specific automations
                target_automations = [
                    'automation.nightly_reboot_with_timer_pause',
                    'automation.startup_restore_timers',
                    'automation.test_timer_pause_resume'
                ]
                
                found_automations = []
                for automation in automation_states:
                    if automation['entity_id'] in target_automations:
                        found_automations.append(automation['entity_id'])
                
                if found_automations:
                    print(f"✅ Found {len(found_automations)} target automations: {', '.join(found_automations)}")
                    return True
                else:
                    print("⚠️  No target automations found (they may not be loaded yet)")
                    return False
            else:
                print(f"❌ Failed to get states: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error testing automations: {e}")
            return False
    
    def test_scripts(self) -> bool:
        """Test if scripts are loaded"""
        try:
            response = self.session.get(f'{self.ha_url}/api/states')
            if response.status_code == 200:
                states = response.json()
                script_states = [s for s in states if s['entity_id'].startswith('script.')]
                
                if script_states:
                    print(f"✅ Found {len(script_states)} scripts loaded")
                    return True
                else:
                    print("⚠️  No scripts found")
                    return False
            else:
                print(f"❌ Failed to get states: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error testing scripts: {e}")
            return False
    
    def test_python_scripts(self) -> bool:
        """Test if Python scripts are accessible"""
        try:
            # Try to call a Python script service
            response = self.session.post(f'{self.ha_url}/api/services/python_script/test_script')
            if response.status_code == 200:
                print("✅ Python scripts are accessible")
                return True
            else:
                print(f"⚠️  Python scripts may not be configured (status: {response.status_code})")
                return False
        except Exception as e:
            print(f"❌ Error testing Python scripts: {e}")
            return False
    
    def test_timer_entities(self) -> bool:
        """Test if timer entities exist"""
        try:
            response = self.session.get(f'{self.ha_url}/api/states')
            if response.status_code == 200:
                states = response.json()
                timer_states = [s for s in states if s['entity_id'].startswith('timer.')]
                
                if timer_states:
                    print(f"✅ Found {len(timer_states)} timer entities")
                    return True
                else:
                    print("⚠️  No timer entities found")
                    return False
            else:
                print(f"❌ Failed to get states: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error testing timer entities: {e}")
            return False
    
    def test_configuration(self) -> bool:
        """Test if configuration is valid"""
        try:
            response = self.session.post(f'{self.ha_url}/api/services/homeassistant/check_config')
            if response.status_code == 200:
                result = response.json()
                if result.get('result') == 'valid':
                    print("✅ Home Assistant configuration is valid")
                    return True
                else:
                    print(f"❌ Configuration validation failed: {result.get('errors', 'Unknown error')}")
                    return False
            else:
                print(f"❌ Failed to check configuration: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error testing configuration: {e}")
            return False
    
    def run_all_tests(self) -> bool:
        """Run all tests and return overall success"""
        print("🔍 Running Home Assistant deployment tests...\n")
        
        tests = [
            ("Connectivity", self.test_connectivity),
            ("Configuration", self.test_configuration),
            ("Timer Entities", self.test_timer_entities),
            ("Scripts", self.test_scripts),
            ("Python Scripts", self.test_python_scripts),
            ("Automations", self.test_automations),
        ]
        
        results = []
        for test_name, test_func in tests:
            print(f"Testing {test_name}...")
            try:
                result = test_func()
                results.append(result)
            except Exception as e:
                print(f"❌ {test_name} test failed with exception: {e}")
                results.append(False)
            print()
        
        passed = sum(results)
        total = len(results)
        
        print(f"📊 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! Deployment appears successful.")
        elif passed >= total * 0.8:
            print("⚠️  Most tests passed, but some issues detected.")
        else:
            print("❌ Multiple test failures detected. Check your deployment.")
        
        return passed >= total * 0.8

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Home Assistant deployment')
    parser.add_argument('--ha-url', default='http://homeassistant.local:8123', 
                       help='Home Assistant URL')
    parser.add_argument('--token', help='Home Assistant API token')
    
    args = parser.parse_args()
    
    if not args.token:
        print("❌ API token is required for testing")
        print("Generate one at: http://homeassistant.local:8123/profile")
        sys.exit(1)
    
    tester = HATester(args.ha_url, args.token)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
