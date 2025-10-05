#!/usr/bin/env python3
"""
Simple Home Assistant Deployment (SSH-based)
Deploys automations safely without requiring API access
"""

import os
import sys
import subprocess
from datetime import datetime

class SimpleDeployer:
    def __init__(self, ha_host="192.168.86.2", ssh_user="root"):
        self.ha_host = ha_host
        self.ssh_user = ssh_user
    
    def create_backup(self):
        """Create a backup of current automations"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"../backup/simple_deploy_{timestamp}"
        os.makedirs(backup_dir, exist_ok=True)
        
        print(f"📦 Creating backup: {backup_dir}")
        
        # Try to backup current automations
        backup_files = [
            "/config/automations.yaml",
            "/config/configuration.yaml"
        ]
        
        for file_path in backup_files:
            try:
                cmd = f"scp {self.ssh_user}@{self.ha_host}:{file_path} {backup_dir}/ 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"  ✅ Backed up: {file_path}")
                else:
                    print(f"  ⚠️  Could not backup: {file_path}")
            except Exception as e:
                print(f"  ⚠️  Backup error for {file_path}: {e}")
        
        return backup_dir
    
    def deploy_automation_file(self, automation_file):
        """Deploy a single automation file"""
        print(f"📤 Deploying: {automation_file}")
        
        try:
            # Copy the automation file to Home Assistant
            cmd = f"scp {automation_file} {self.ssh_user}@{self.ha_host}:/config/automations/"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"  ✅ File copied successfully")
                return True
            else:
                print(f"  ❌ Copy failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"  ❌ Deployment error: {e}")
            return False
    
    def deploy_configuration(self, config_file):
        """Deploy configuration file"""
        print(f"📤 Deploying configuration: {config_file}")
        
        try:
            # Copy the configuration file to Home Assistant
            cmd = f"scp {config_file} {self.ssh_user}@{self.ha_host}:/config/configuration.yaml"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"  ✅ Configuration copied successfully")
                return True
            else:
                print(f"  ❌ Configuration copy failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"  ❌ Configuration deployment error: {e}")
            return False
    
    def restart_home_assistant(self):
        """Restart Home Assistant"""
        print("🔄 Restarting Home Assistant...")
        
        try:
            # Try different restart methods
            restart_commands = [
                "systemctl restart home-assistant@homeassistant",
                "systemctl restart homeassistant", 
                "ha core restart",
                "homeassistant restart",
                "supervisor restart core"
            ]
            
            for cmd in restart_commands:
                full_cmd = f"ssh {self.ssh_user}@{self.ha_host} '{cmd}' 2>/dev/null"
                result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"  ✅ Restart command successful: {cmd}")
                    return True
            
            print("  ⚠️  No restart command worked - Home Assistant may need manual restart")
            return False
            
        except Exception as e:
            print(f"  ❌ Restart error: {e}")
            return False
    
    def verify_deployment(self):
        """Verify deployment by checking if Home Assistant is responsive"""
        print("🔍 Verifying deployment...")
        
        try:
            # Wait a bit for restart
            import time
            time.sleep(10)
            
            # Check if Home Assistant is responding
            cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://{self.ha_host}:8123/"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip() in ['200', '302']:
                print("  ✅ Home Assistant is responding")
                return True
            else:
                print(f"  ⚠️  Home Assistant response: {result.stdout.strip()}")
                return False
                
        except Exception as e:
            print(f"  ❌ Verification error: {e}")
            return False
    
    def safe_deploy(self, automation_file, config_file=None):
        """Safely deploy automation and configuration"""
        print(f"🚀 SAFE DEPLOYMENT: {automation_file}")
        print("=" * 50)
        
        # Step 1: Create backup
        backup_dir = self.create_backup()
        
        try:
            # Step 2: Deploy automation file
            if not self.deploy_automation_file(automation_file):
                print("❌ DEPLOYMENT FAILED: Could not deploy automation file")
                return False
            
            # Step 3: Deploy configuration if provided
            if config_file and os.path.exists(config_file):
                if not self.deploy_configuration(config_file):
                    print("❌ DEPLOYMENT FAILED: Could not deploy configuration")
                    return False
            
            # Step 4: Restart Home Assistant
            if not self.restart_home_assistant():
                print("⚠️  WARNING: Could not restart Home Assistant automatically")
                print("   You may need to restart it manually from the web UI")
            
            # Step 5: Verify deployment
            if not self.verify_deployment():
                print("⚠️  WARNING: Could not verify deployment")
                print("   Check Home Assistant web UI manually")
            
            print("\n🎉 DEPLOYMENT COMPLETED!")
            print(f"📦 Backup available at: {backup_dir}")
            print("\n📋 Next steps:")
            print("1. Check Home Assistant web UI")
            print("2. Verify automations are loaded")
            print("3. Test automation functionality")
            
            return True
            
        except Exception as e:
            print(f"❌ DEPLOYMENT ERROR: {e}")
            print(f"📦 Backup available for restore: {backup_dir}")
            return False

def main():
    if len(sys.argv) < 2:
        print("Simple Home Assistant Deployment")
        print("Usage:")
        print("  python3 simple_deploy.py <automation_file> [config_file]")
        print("")
        print("Examples:")
        print("  python3 simple_deploy.py automations/my_automation.yaml")
        print("  python3 simple_deploy.py automations/my_automation.yaml configuration.yaml")
        sys.exit(1)
    
    automation_file = sys.argv[1]
    config_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(automation_file):
        print(f"❌ Automation file not found: {automation_file}")
        sys.exit(1)
    
    deployer = SimpleDeployer()
    
    if deployer.safe_deploy(automation_file, config_file):
        print("\n✅ DEPLOYMENT SUCCESSFUL!")
        sys.exit(0)
    else:
        print("\n❌ DEPLOYMENT FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    main()
