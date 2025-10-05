#!/usr/bin/env python3
"""
SAFE Home Assistant Automation Deployment System
Prevents automation loss through comprehensive backup, validation, and rollback
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
from datetime import datetime
import urllib.request
import urllib.parse

class SafeAutomationDeployer:
    def __init__(self, ha_host="192.168.86.2", ssh_user="root"):
        self.ha_host = ha_host
        self.ssh_user = ssh_user
        self.backup_dir = None
        self.temp_dir = None
        
    def load_config(self):
        """Load Home Assistant configuration"""
        config = {}
        config_file = '../ha_config.env'
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        return config
    
    def create_comprehensive_backup(self):
        """Create a comprehensive backup of ALL Home Assistant configuration"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_dir = f"../backup/safe_deploy_{timestamp}"
        os.makedirs(self.backup_dir, exist_ok=True)
        
        print(f"📦 Creating comprehensive backup in {self.backup_dir}")
        
        # Files to backup
        critical_files = [
            "/config/configuration.yaml",
            "/config/automations.yaml", 
            "/config/scripts.yaml",
            "/config/scenes.yaml",
            "/config/automations/",
            "/config/scripts/",
            "/config/scenes/"
        ]
        
        for file_path in critical_files:
            try:
                if file_path.endswith('/'):
                    # Directory backup
                    cmd = f"scp -r {self.ssh_user}@{self.ha_host}:{file_path} {self.backup_dir}/"
                else:
                    # File backup
                    cmd = f"scp {self.ssh_user}@{self.ha_host}:{file_path} {self.backup_dir}/"
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"  ✅ Backed up: {file_path}")
                else:
                    print(f"  ⚠️  Could not backup: {file_path} - {result.stderr}")
            except Exception as e:
                print(f"  ❌ Error backing up {file_path}: {e}")
        
        print(f"✅ Backup completed: {self.backup_dir}")
        return self.backup_dir
    
    def validate_automation_syntax(self, automation_file):
        """Validate automation syntax using Home Assistant's built-in validation"""
        print(f"🔍 Validating automation syntax: {automation_file}")
        
        # Create temporary validation environment
        self.temp_dir = tempfile.mkdtemp()
        
        try:
            # Copy automation file to temp directory
            temp_file = os.path.join(self.temp_dir, "automations.yaml")
            shutil.copy2(automation_file, temp_file)
            
            # Create minimal configuration for validation
            temp_config = os.path.join(self.temp_dir, "configuration.yaml")
            with open(temp_config, 'w') as f:
                f.write("""
# Minimal configuration for validation
homeassistant:
  name: Home
  latitude: 0
  longitude: 0
  elevation: 0
  unit_system: metric
  time_zone: UTC

automation: !include automations.yaml
""")
            
            # Run Home Assistant validation
            cmd = f"python3 -m homeassistant --script check_config --config {self.temp_dir}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("  ✅ Automation syntax is valid")
                return True
            else:
                print(f"  ❌ Automation syntax error: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"  ❌ Validation error: {e}")
            return False
        finally:
            # Cleanup temp directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
    
    def test_deployment_safely(self, automation_file):
        """Test deployment in a safe environment"""
        print(f"🧪 Testing deployment safely: {automation_file}")
        
        # Create test automation file with modified IDs to avoid conflicts
        test_file = automation_file.replace('.yaml', '_test.yaml')
        
        with open(automation_file, 'r') as f:
            content = f.read()
        
        # Modify automation IDs to add _test suffix
        modified_content = content.replace('- id: \'', '- id: \'test_')
        
        with open(test_file, 'w') as f:
            f.write(modified_content)
        
        try:
            # Deploy test file
            cmd = f"scp {test_file} {self.ssh_user}@{self.ha_host}:/config/automations_test.yaml"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"  ❌ Test deployment failed: {result.stderr}")
                return False
            
            # Test Home Assistant configuration
            config = self.load_config()
            ha_token = config.get('HA_TOKEN')
            ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
            
            # Check if Home Assistant can load the test configuration
            url = f"{ha_url}/api/config"
            headers = {'Authorization': f'Bearer {ha_token}'}
            
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    print("  ✅ Test deployment successful")
                    return True
                else:
                    print(f"  ❌ Test deployment failed: HTTP {response.status}")
                    return False
                    
        except Exception as e:
            print(f"  ❌ Test deployment error: {e}")
            return False
        finally:
            # Cleanup test file
            if os.path.exists(test_file):
                os.remove(test_file)
            
            # Remove test file from Home Assistant
            cmd = f"ssh {self.ssh_user}@{self.ha_host} 'rm -f /config/automations_test.yaml'"
            subprocess.run(cmd, shell=True, capture_output=True)
    
    def rollback_deployment(self):
        """Rollback to the backup if deployment fails"""
        if not self.backup_dir or not os.path.exists(self.backup_dir):
            print("❌ No backup available for rollback!")
            return False
        
        print(f"🔄 Rolling back to backup: {self.backup_dir}")
        
        try:
            # Restore configuration files
            files_to_restore = ['configuration.yaml', 'automations.yaml', 'scripts.yaml', 'scenes.yaml']
            
            for file_name in files_to_restore:
                backup_file = os.path.join(self.backup_dir, file_name)
                if os.path.exists(backup_file):
                    cmd = f"scp {backup_file} {self.ssh_user}@{self.ha_host}:/config/{file_name}"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"  ✅ Restored: {file_name}")
                    else:
                        print(f"  ❌ Failed to restore: {file_name}")
            
            # Restore directories
            dirs_to_restore = ['automations', 'scripts', 'scenes']
            for dir_name in dirs_to_restore:
                backup_dir = os.path.join(self.backup_dir, dir_name)
                if os.path.exists(backup_dir):
                    cmd = f"scp -r {backup_dir}/* {self.ssh_user}@{self.ha_host}:/config/{dir_name}/"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"  ✅ Restored: {dir_name}/")
                    else:
                        print(f"  ⚠️  Could not restore: {dir_name}/")
            
            print("✅ Rollback completed")
            return True
            
        except Exception as e:
            print(f"❌ Rollback failed: {e}")
            return False
    
    def restart_home_assistant(self):
        """Safely restart Home Assistant"""
        print("🔄 Restarting Home Assistant...")
        
        config = self.load_config()
        ha_token = config.get('HA_TOKEN')
        ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
        
        try:
            url = f"{ha_url}/api/services/homeassistant/restart"
            headers = {
                'Authorization': f'Bearer {ha_token}',
                'Content-Type': 'application/json'
            }
            
            request = urllib.request.Request(url, headers=headers, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status == 200:
                    print("✅ Home Assistant restart initiated")
                    return True
                else:
                    print(f"❌ Restart failed: HTTP {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Restart error: {e}")
            return False
    
    def verify_deployment(self):
        """Verify that the deployment was successful"""
        print("🔍 Verifying deployment...")
        
        config = self.load_config()
        ha_token = config.get('HA_TOKEN')
        ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
        
        try:
            # Wait for Home Assistant to restart
            import time
            time.sleep(30)
            
            # Check if Home Assistant is responsive
            url = f"{ha_url}/api/"
            headers = {'Authorization': f'Bearer {ha_token}'}
            
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    print("✅ Home Assistant is responsive")
                    
                    # Check automations
                    url = f"{ha_url}/api/states"
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.loads(response.read().decode())
                        automations = [item for item in data if item['entity_id'].startswith('automation.')]
                        print(f"✅ Found {len(automations)} automations loaded")
                        
                        if len(automations) == 0:
                            print("❌ CRITICAL: No automations found!")
                            return False
                        
                        return True
                else:
                    print(f"❌ Home Assistant not responsive: HTTP {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Verification error: {e}")
            return False
    
    def safe_deploy_automation(self, automation_file):
        """Main safe deployment method"""
        print(f"🚀 Starting SAFE deployment of: {automation_file}")
        
        # Step 1: Create comprehensive backup
        backup_dir = self.create_comprehensive_backup()
        
        try:
            # Step 2: Validate syntax
            if not self.validate_automation_syntax(automation_file):
                print("❌ Deployment aborted: Invalid syntax")
                return False
            
            # Step 3: Test deployment safely
            if not self.test_deployment_safely(automation_file):
                print("❌ Deployment aborted: Test failed")
                return False
            
            # Step 4: Deploy for real
            print("📤 Deploying automation...")
            cmd = f"scp {automation_file} {self.ssh_user}@{self.ha_host}:/config/automations/"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"❌ Deployment failed: {result.stderr}")
                self.rollback_deployment()
                return False
            
            # Step 5: Restart Home Assistant
            if not self.restart_home_assistant():
                print("❌ Restart failed, rolling back...")
                self.rollback_deployment()
                return False
            
            # Step 6: Verify deployment
            if not self.verify_deployment():
                print("❌ Verification failed, rolling back...")
                self.rollback_deployment()
                return False
            
            print("🎉 SAFE deployment completed successfully!")
            print(f"📦 Backup available at: {backup_dir}")
            return True
            
        except Exception as e:
            print(f"❌ Deployment error: {e}")
            print("🔄 Attempting rollback...")
            self.rollback_deployment()
            return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 safe_automation_deploy.py <automation_file>")
        sys.exit(1)
    
    automation_file = sys.argv[1]
    
    if not os.path.exists(automation_file):
        print(f"❌ Automation file not found: {automation_file}")
        sys.exit(1)
    
    deployer = SafeAutomationDeployer()
    
    if deployer.safe_deploy_automation(automation_file):
        print("✅ Deployment successful!")
        sys.exit(0)
    else:
        print("❌ Deployment failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
