#!/usr/bin/env python3
"""
Home Assistant Configuration Deployment Script
Deploys automations, scripts, and Python scripts to Home Assistant Green box
"""

import os
import sys
import json
import requests
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Optional

class HADeployer:
    def __init__(self, ha_url: str, token: str = None, ssh_user: str = None, ssh_host: str = None):
        self.ha_url = ha_url.rstrip('/')
        self.token = token
        self.ssh_user = ssh_user
        self.ssh_host = ssh_host or 'homeassistant.local'
        self.session = requests.Session()
        
        if self.token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json'
            })
    
    def test_connection(self) -> bool:
        """Test connection to Home Assistant"""
        try:
            if self.token:
                response = self.session.get(f'{self.ha_url}/api/')
                return response.status_code == 200
            else:
                # Test SSH connection
                result = subprocess.run(
                    ['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes', 
                     f'{self.ssh_user}@{self.ssh_host}', 'echo "SSH connection successful"'],
                    capture_output=True, text=True, timeout=10
                )
                return result.returncode == 0
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False
    
    def deploy_via_ssh(self, local_path: str, remote_path: str) -> bool:
        """Deploy files via SSH using scp"""
        try:
            # Create remote directory if it doesn't exist
            subprocess.run([
                'ssh', f'{self.ssh_user}@{self.ssh_host}',
                f'mkdir -p {os.path.dirname(remote_path)}'
            ], check=True, timeout=30)
            
            # Copy file
            subprocess.run([
                'scp', local_path, f'{self.ssh_user}@{self.ssh_host}:{remote_path}'
            ], check=True, timeout=30)
            
            print(f"✓ Deployed {local_path} to {remote_path}")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"✗ SSH deployment failed for {local_path}: {e}")
            return False
        except Exception as e:
            print(f"✗ SSH deployment error for {local_path}: {e}")
            return False
    
    def deploy_via_api(self, file_path: str, file_type: str) -> bool:
        """Deploy configuration via Home Assistant API"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # For automations and scripts, we need to reload them
            if file_type in ['automation', 'script']:
                # First, we'd need to upload the file (this requires file upload API)
                # For now, we'll just trigger a reload
                response = self.session.post(f'{self.ha_url}/api/services/{file_type}/reload')
                if response.status_code == 200:
                    print(f"✓ Reloaded {file_type}s")
                    return True
                else:
                    print(f"✗ Failed to reload {file_type}s: {response.text}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"✗ API deployment failed for {file_path}: {e}")
            return False
    
    def deploy_python_script(self, script_path: str) -> bool:
        """Deploy Python script to Home Assistant"""
        remote_path = f'/config/python_scripts/{os.path.basename(script_path)}'
        return self.deploy_via_ssh(script_path, remote_path)
    
    def deploy_automation(self, automation_path: str) -> bool:
        """Deploy automation to Home Assistant"""
        remote_path = f'/config/automations/{os.path.basename(automation_path)}'
        return self.deploy_via_ssh(automation_path, remote_path)
    
    def deploy_script(self, script_path: str) -> bool:
        """Deploy script to Home Assistant"""
        remote_path = f'/config/scripts/{os.path.basename(script_path)}'
        return self.deploy_via_ssh(script_path, remote_path)
    
    def update_configuration(self, config_path: str) -> bool:
        """Update Home Assistant configuration"""
        remote_path = '/config/configuration.yaml'
        return self.deploy_via_ssh(config_path, remote_path)
    
    def restart_homeassistant(self) -> bool:
        """Restart Home Assistant"""
        try:
            if self.token:
                response = self.session.post(f'{self.ha_url}/api/services/homeassistant/restart')
                return response.status_code == 200
            else:
                subprocess.run([
                    'ssh', f'{self.ssh_user}@{self.ssh_host}',
                    'ha core restart'
                ], check=True, timeout=60)
                return True
        except Exception as e:
            print(f"✗ Failed to restart Home Assistant: {e}")
            return False
    
    def deploy_all(self, source_dir: str) -> bool:
        """Deploy all configurations from source directory"""
        source_path = Path(source_dir)
        success_count = 0
        total_count = 0
        
        print(f"🚀 Starting deployment from {source_dir}")
        print(f"📡 Target: {self.ha_url if self.token else f'{self.ssh_user}@{self.ssh_host}'}")
        
        # Deploy Python scripts
        python_scripts_dir = source_path / 'python_scripts'
        if python_scripts_dir.exists():
            print("\n📜 Deploying Python scripts...")
            for script_file in python_scripts_dir.glob('*.py'):
                total_count += 1
                if self.deploy_python_script(str(script_file)):
                    success_count += 1
        
        # Deploy automations
        automations_dir = source_path / 'automations'
        if automations_dir.exists():
            print("\n🤖 Deploying automations...")
            for automation_file in automations_dir.glob('*.yaml'):
                total_count += 1
                if self.deploy_automation(str(automation_file)):
                    success_count += 1
        
        # Deploy scripts
        scripts_dir = source_path / 'scripts'
        if scripts_dir.exists():
            print("\n⚙️ Deploying scripts...")
            for script_file in scripts_dir.glob('*.yaml'):
                total_count += 1
                if self.deploy_script(str(script_file)):
                    success_count += 1
        
        # Update configuration
        config_file = source_path / 'configuration.yaml'
        if config_file.exists():
            print("\n⚙️ Updating configuration...")
            total_count += 1
            if self.update_configuration(str(config_file)):
                success_count += 1
        
        print(f"\n📊 Deployment Summary: {success_count}/{total_count} files deployed successfully")
        
        if success_count == total_count and total_count > 0:
            print("\n🔄 Restarting Home Assistant...")
            if self.restart_homeassistant():
                print("✅ Home Assistant restarted successfully")
                return True
            else:
                print("⚠️ Files deployed but restart failed")
                return False
        
        return success_count == total_count

def main():
    parser = argparse.ArgumentParser(description='Deploy Home Assistant configurations')
    parser.add_argument('--ha-url', default='http://homeassistant.local:8123', 
                       help='Home Assistant URL')
    parser.add_argument('--token', help='Home Assistant API token')
    parser.add_argument('--ssh-user', help='SSH username')
    parser.add_argument('--ssh-host', default='homeassistant.local', 
                       help='SSH hostname')
    parser.add_argument('--source-dir', default='.', 
                       help='Source directory containing configs')
    parser.add_argument('--test-only', action='store_true', 
                       help='Only test connection, do not deploy')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.token and not args.ssh_user:
        print("❌ Error: Must provide either --token for API or --ssh-user for SSH")
        sys.exit(1)
    
    deployer = HADeployer(
        ha_url=args.ha_url,
        token=args.token,
        ssh_user=args.ssh_user,
        ssh_host=args.ssh_host
    )
    
    # Test connection
    print("🔍 Testing connection...")
    if not deployer.test_connection():
        print("❌ Connection test failed")
        sys.exit(1)
    print("✅ Connection successful")
    
    if args.test_only:
        print("✅ Connection test passed")
        return
    
    # Deploy configurations
    success = deployer.deploy_all(args.source_dir)
    
    if success:
        print("\n🎉 Deployment completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Deployment failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
