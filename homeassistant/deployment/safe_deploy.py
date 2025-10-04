#!/usr/bin/env python3
"""
Safe Home Assistant Configuration Deployment Script
Merges new timer management features with existing configuration
"""

import os
import sys
import yaml
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List

class SafeHADeployer:
    def __init__(self, ha_host: str, ssh_user: str = "root"):
        self.ha_host = ha_host
        self.ssh_user = ssh_user
        self.backup_dir = Path(f"../backup/{self._get_timestamp()}")
        self.source_dir = Path("..")
        
    def _get_timestamp(self) -> str:
        """Get current timestamp for backup directory"""
        import datetime
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def backup_existing_config(self) -> bool:
        """Backup existing Home Assistant configuration"""
        try:
            print(f"📦 Creating backup in {self.backup_dir}")
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Backup configuration.yaml
            subprocess.run([
                'scp', f'{self.ssh_user}@{self.ha_host}:/config/configuration.yaml',
                str(self.backup_dir / 'configuration.yaml')
            ], check=True, timeout=30)
            
            # Backup existing directories
            for dir_name in ['automations', 'scripts', 'python_scripts']:
                try:
                    subprocess.run([
                        'ssh', f'{self.ssh_user}@{self.ha_host}',
                        f'mkdir -p /tmp/ha_backup && cp -r /config/{dir_name} /tmp/ha_backup/ 2>/dev/null || true'
                    ], check=True, timeout=30)
                    
                    subprocess.run([
                        'scp', '-r', f'{self.ssh_user}@{self.ha_host}:/tmp/ha_backup/{dir_name}',
                        str(self.backup_dir)
                    ], check=True, timeout=30)
                except:
                    print(f"⚠️  No existing {dir_name} directory found")
            
            # Cleanup temp files
            subprocess.run([
                'ssh', f'{self.ssh_user}@{self.ha_host}', 'rm -rf /tmp/ha_backup'
            ], check=True, timeout=30)
            
            print("✅ Backup completed successfully")
            return True
            
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False
    
    def merge_configuration(self) -> str:
        """Merge timer management config with existing configuration"""
        try:
            # Load existing configuration
            existing_config_path = self.backup_dir / 'configuration.yaml'
            if existing_config_path.exists():
                with open(existing_config_path, 'r') as f:
                    existing_config = yaml.safe_load(f) or {}
            else:
                existing_config = {}
            
            # Load our new configuration
            new_config_path = self.source_dir / 'configuration.yaml'
            with open(new_config_path, 'r') as f:
                new_config = yaml.safe_load(f)
            
            # Merge configurations
            merged_config = existing_config.copy()
            
            # Add new sections if they don't exist
            for key, value in new_config.items():
                if key not in merged_config:
                    merged_config[key] = value
                elif key == 'automation' and isinstance(value, str) and 'automations/' in value:
                    # Handle automation directory inclusion
                    if 'automation: !include automations.yaml' in str(merged_config.get('automation', '')):
                        # Replace single file include with directory include
                        merged_config[key] = value
                    elif isinstance(merged_config[key], str) and 'automations.yaml' in merged_config[key]:
                        # Keep existing automation setup, add our directory
                        merged_config[key] = [merged_config[key], value]
                elif key == 'script' and isinstance(value, str) and 'scripts/' in value:
                    # Handle script directory inclusion
                    if 'script: !include scripts.yaml' in str(merged_config.get('script', '')):
                        # Replace single file include with directory include
                        merged_config[key] = value
                    elif isinstance(merged_config[key], str) and 'scripts.yaml' in merged_config[key]:
                        # Keep existing script setup, add our directory
                        merged_config[key] = [merged_config[key], value]
            
            # Create merged configuration content
            merged_content = []
            merged_content.append("# Home Assistant Configuration")
            merged_content.append("# Merged with timer management features")
            merged_content.append("")
            
            # Add existing content with modifications
            if existing_config_path.exists():
                with open(existing_config_path, 'r') as f:
                    original_lines = f.readlines()
                
                in_automation_section = False
                in_script_section = False
                automation_added = False
                script_added = False
                
                for line in original_lines:
                    line_stripped = line.strip()
                    
                    if line_stripped.startswith('automation:'):
                        in_automation_section = True
                        # Keep existing automation line
                        merged_content.append(line.rstrip())
                        if 'automations.yaml' in line:
                            # Add our directory include as well
                            merged_content.append("automation_timer: !include_dir_list automations/")
                        automation_added = True
                    elif line_stripped.startswith('script:'):
                        in_script_section = True
                        # Keep existing script line
                        merged_content.append(line.rstrip())
                        if 'scripts.yaml' in line:
                            # Add our directory include as well
                            merged_content.append("script_timer: !include_dir_list scripts/")
                        script_added = True
                    elif line_stripped and not line_stripped.startswith('#') and ':' in line_stripped:
                        # End of section
                        in_automation_section = False
                        in_script_section = False
                        merged_content.append(line.rstrip())
                    else:
                        merged_content.append(line.rstrip())
            
            # Add new sections at the end
            merged_content.append("")
            merged_content.append("# Timer Management Configuration")
            merged_content.append("input_text:")
            merged_content.append("  timer_states:")
            merged_content.append('    name: "Timer States Storage"')
            merged_content.append('    initial: "{}"')
            merged_content.append("    max: 10000")
            merged_content.append("")
            merged_content.append("python_script:")
            merged_content.append("")
            
            # Write merged configuration
            merged_config_path = self.source_dir / 'configuration_merged.yaml'
            with open(merged_config_path, 'w') as f:
                f.write('\n'.join(merged_content))
            
            print("✅ Configuration merged successfully")
            return str(merged_config_path)
            
        except Exception as e:
            print(f"❌ Configuration merge failed: {e}")
            return None
    
    def deploy_files_safely(self) -> bool:
        """Deploy files without overwriting existing ones"""
        try:
            print("🚀 Deploying files safely...")
            
            # Create directories
            subprocess.run([
                'ssh', f'{self.ssh_user}@{self.ha_host}',
                'mkdir -p /config/{automations,scripts,python_scripts}'
            ], check=True, timeout=30)
            
            # Deploy Python scripts
            python_scripts_dir = self.source_dir / 'python_scripts'
            if python_scripts_dir.exists():
                print("📜 Deploying Python scripts...")
                subprocess.run([
                    'scp', f'{python_scripts_dir}/*.py',
                    f'{self.ssh_user}@{self.ha_host}:/config/python_scripts/'
                ], check=True, timeout=30)
            
            # Deploy automations
            automations_dir = self.source_dir / 'automations'
            if automations_dir.exists():
                print("🤖 Deploying automations...")
                subprocess.run([
                    'scp', f'{automations_dir}/*.yaml',
                    f'{self.ssh_user}@{self.ha_host}:/config/automations/'
                ], check=True, timeout=30)
            
            # Deploy scripts
            scripts_dir = self.source_dir / 'scripts'
            if scripts_dir.exists():
                print("⚙️ Deploying scripts...")
                subprocess.run([
                    'scp', f'{scripts_dir}/*.yaml',
                    f'{self.ssh_user}@{self.ha_host}:/config/scripts/'
                ], check=True, timeout=30)
            
            return True
            
        except Exception as e:
            print(f"❌ File deployment failed: {e}")
            return False
    
    def deploy_merged_configuration(self, merged_config_path: str) -> bool:
        """Deploy the merged configuration"""
        try:
            print("⚙️ Deploying merged configuration...")
            subprocess.run([
                'scp', merged_config_path,
                f'{self.ssh_user}@{self.ha_host}:/config/configuration.yaml'
            ], check=True, timeout=30)
            return True
        except Exception as e:
            print(f"❌ Configuration deployment failed: {e}")
            return False
    
    def restart_homeassistant(self) -> bool:
        """Restart Home Assistant"""
        try:
            print("🔄 Restarting Home Assistant...")
            subprocess.run([
                'ssh', f'{self.ssh_user}@{self.ha_host}', 'ha core restart'
            ], check=True, timeout=60)
            print("✅ Home Assistant restart initiated")
            return True
        except Exception as e:
            print(f"❌ Restart failed: {e}")
            return False
    
    def deploy_all(self) -> bool:
        """Perform complete safe deployment"""
        print("🚀 Starting safe deployment...")
        
        # Step 1: Backup existing configuration
        if not self.backup_existing_config():
            return False
        
        # Step 2: Merge configurations
        merged_config_path = self.merge_configuration()
        if not merged_config_path:
            return False
        
        # Step 3: Deploy files
        if not self.deploy_files_safely():
            return False
        
        # Step 4: Deploy merged configuration
        if not self.deploy_merged_configuration(merged_config_path):
            return False
        
        # Step 5: Restart Home Assistant
        if not self.restart_homeassistant():
            print("⚠️  Deployment completed but restart failed")
            return False
        
        print("🎉 Safe deployment completed successfully!")
        print(f"📦 Backup available at: {self.backup_dir}")
        return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Safe Home Assistant deployment')
    parser.add_argument('--host', default='192.168.86.2', help='Home Assistant hostname')
    parser.add_argument('--ssh-user', default='root', help='SSH username')
    
    args = parser.parse_args()
    
    deployer = SafeHADeployer(args.host, args.ssh_user)
    success = deployer.deploy_all()
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
