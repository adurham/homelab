#!/usr/bin/env python3
"""
Home Assistant Automation Backup and Restore System
Provides comprehensive backup and restore capabilities for automations
"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime
import urllib.request
import urllib.parse

class AutomationBackupRestore:
    def __init__(self, ha_host="192.168.86.2", ssh_user="root"):
        self.ha_host = ha_host
        self.ssh_user = ssh_user
        
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
    
    def create_automation_backup(self, backup_name=None):
        """Create a comprehensive backup of all automations"""
        if not backup_name:
            backup_name = f"automation_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        backup_dir = f"../backup/{backup_name}"
        os.makedirs(backup_dir, exist_ok=True)
        
        print(f"📦 Creating automation backup: {backup_name}")
        
        # Backup automation files
        automation_files = [
            "/config/automations.yaml",
            "/config/automations/",
            "/config/scripts.yaml", 
            "/config/scripts/",
            "/config/scenes.yaml",
            "/config/scenes/"
        ]
        
        for file_path in automation_files:
            try:
                if file_path.endswith('/'):
                    # Directory backup
                    cmd = f"scp -r {self.ssh_user}@{self.ha_host}:{file_path} {backup_dir}/"
                else:
                    # File backup
                    cmd = f"scp {self.ssh_user}@{self.ha_host}:{file_path} {backup_dir}/"
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"  ✅ Backed up: {file_path}")
                else:
                    print(f"  ⚠️  Could not backup: {file_path}")
            except Exception as e:
                print(f"  ❌ Error backing up {file_path}: {e}")
        
        # Also backup via API to get current state
        self.backup_automations_via_api(backup_dir)
        
        print(f"✅ Backup completed: {backup_dir}")
        return backup_dir
    
    def backup_automations_via_api(self, backup_dir):
        """Backup automations via Home Assistant API"""
        config = self.load_config()
        ha_token = config.get('HA_TOKEN')
        ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
        
        try:
            # Get all automations via API
            url = f"{ha_url}/api/states"
            headers = {'Authorization': f'Bearer {ha_token}'}
            
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                automations = [item for item in data if item['entity_id'].startswith('automation.')]
                
                # Save automation states to JSON
                api_backup_file = os.path.join(backup_dir, "automations_api_backup.json")
                with open(api_backup_file, 'w') as f:
                    json.dump(automations, f, indent=2)
                
                print(f"  ✅ API backup: {len(automations)} automations saved")
                
        except Exception as e:
            print(f"  ⚠️  API backup failed: {e}")
    
    def list_available_backups(self):
        """List all available backups"""
        backup_base = "../backup"
        if not os.path.exists(backup_base):
            print("No backups found")
            return []
        
        backups = []
        for item in os.listdir(backup_base):
            item_path = os.path.join(backup_base, item)
            if os.path.isdir(item_path):
                # Get modification time
                mtime = os.path.getmtime(item_path)
                mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                backups.append((item, mtime_str, item_path))
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x[1], reverse=True)
        
        print("📦 Available backups:")
        for i, (name, mtime, path) in enumerate(backups):
            print(f"  {i+1}. {name} ({mtime})")
        
        return backups
    
    def restore_automations(self, backup_name):
        """Restore automations from backup"""
        backup_dir = f"../backup/{backup_name}"
        
        if not os.path.exists(backup_dir):
            print(f"❌ Backup not found: {backup_name}")
            return False
        
        print(f"🔄 Restoring automations from: {backup_name}")
        
        # Create a backup before restoring
        current_backup = self.create_automation_backup(f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        
        try:
            # Restore automation files
            files_to_restore = ['automations.yaml', 'scripts.yaml', 'scenes.yaml']
            
            for file_name in files_to_restore:
                backup_file = os.path.join(backup_dir, file_name)
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
                backup_dir_path = os.path.join(backup_dir, dir_name)
                if os.path.exists(backup_dir_path):
                    cmd = f"scp -r {backup_dir_path}/* {self.ssh_user}@{self.ha_host}:/config/{dir_name}/"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"  ✅ Restored: {dir_name}/")
                    else:
                        print(f"  ⚠️  Could not restore: {dir_name}/")
            
            # Restart Home Assistant
            print("🔄 Restarting Home Assistant...")
            config = self.load_config()
            ha_token = config.get('HA_TOKEN')
            ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
            
            url = f"{ha_url}/api/services/homeassistant/restart"
            headers = {
                'Authorization': f'Bearer {ha_token}',
                'Content-Type': 'application/json'
            }
            
            request = urllib.request.Request(url, headers=headers, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status == 200:
                    print("✅ Home Assistant restart initiated")
                    
                    # Wait and verify
                    import time
                    time.sleep(30)
                    
                    # Verify restoration
                    url = f"{ha_url}/api/states"
                    headers = {'Authorization': f'Bearer {ha_token}'}
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.loads(response.read().decode())
                        automations = [item for item in data if item['entity_id'].startswith('automation.')]
                        print(f"✅ Verification: {len(automations)} automations loaded")
                        
                        if len(automations) == 0:
                            print("❌ CRITICAL: No automations found after restore!")
                            print(f"🔄 Rolling back to: {current_backup}")
                            self.restore_automations(os.path.basename(current_backup))
                            return False
                        
                        print("🎉 Restoration completed successfully!")
                        print(f"📦 Current backup available at: {current_backup}")
                        return True
                else:
                    print(f"❌ Restart failed: HTTP {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Restoration error: {e}")
            print(f"🔄 Rolling back to: {current_backup}")
            self.restore_automations(os.path.basename(current_backup))
            return False
    
    def create_automation_from_webui(self):
        """Create automation backup from current web UI state"""
        print("📱 Creating automation backup from current web UI state...")
        
        config = self.load_config()
        ha_token = config.get('HA_TOKEN')
        ha_url = config.get('HA_URL', f'http://{self.ha_host}:8123')
        
        try:
            # Get all automations via API
            url = f"{ha_url}/api/states"
            headers = {'Authorization': f'Bearer {ha_token}'}
            
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
                automations = [item for item in data if item['entity_id'].startswith('automation.')]
                
                if len(automations) == 0:
                    print("❌ No automations found in web UI!")
                    return False
                
                # Create backup directory
                backup_name = f"webui_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_dir = f"../backup/{backup_name}"
                os.makedirs(backup_dir, exist_ok=True)
                
                # Save automations as JSON
                api_backup_file = os.path.join(backup_dir, "automations_webui.json")
                with open(api_backup_file, 'w') as f:
                    json.dump(automations, f, indent=2)
                
                # Create a basic automations.yaml file
                automations_yaml = os.path.join(backup_dir, "automations.yaml")
                with open(automations_yaml, 'w') as f:
                    f.write("# Automations backed up from web UI\n")
                    f.write("# This file contains the current state of all automations\n\n")
                    
                    for automation in automations:
                        f.write(f"# {automation['attributes'].get('friendly_name', 'Unknown')}\n")
                        f.write(f"# ID: {automation['attributes'].get('id', 'unknown')}\n")
                        f.write(f"# State: {automation['state']}\n")
                        f.write(f"# Last triggered: {automation['attributes'].get('last_triggered', 'never')}\n")
                        f.write("# Note: Full automation definition not available via API\n\n")
                
                print(f"✅ Web UI backup created: {backup_dir}")
                print(f"📄 {len(automations)} automations backed up")
                print(f"📁 Files created:")
                print(f"  - {api_backup_file}")
                print(f"  - {automations_yaml}")
                
                return backup_dir
                
        except Exception as e:
            print(f"❌ Web UI backup error: {e}")
            return False

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 automation_backup_restore.py backup [name]")
        print("  python3 automation_backup_restore.py restore <backup_name>")
        print("  python3 automation_backup_restore.py list")
        print("  python3 automation_backup_restore.py webui")
        sys.exit(1)
    
    command = sys.argv[1]
    backup_restore = AutomationBackupRestore()
    
    if command == "backup":
        backup_name = sys.argv[2] if len(sys.argv) > 2 else None
        backup_restore.create_automation_backup(backup_name)
        
    elif command == "restore":
        if len(sys.argv) < 3:
            print("❌ Please specify backup name")
            sys.exit(1)
        backup_name = sys.argv[2]
        backup_restore.restore_automations(backup_name)
        
    elif command == "list":
        backup_restore.list_available_backups()
        
    elif command == "webui":
        backup_restore.create_automation_from_webui()
        
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
