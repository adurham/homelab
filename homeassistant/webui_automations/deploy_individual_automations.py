#!/usr/bin/env python3
"""
Deploy individual automation files back to Home Assistant
"""

import os
import subprocess
import glob
from pathlib import Path

def deploy_automations(ha_host="192.168.86.2", ssh_user="root"):
    """Deploy all individual automation files to Home Assistant"""
    
    print("🚀 Deploying individual automations to Home Assistant...")
    
    # Create backup of existing automations.yaml
    print("📦 Creating backup of existing automations...")
    try:
        subprocess.run([
            'ssh', f'{ssh_user}@{ha_host}',
            'cp /config/automations.yaml /config/automations.yaml.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true'
        ], check=True, timeout=30)
        print("✅ Backup created")
    except Exception as e:
        print(f"⚠️  Backup failed: {e}")
    
    # Create automations directory structure
    print("📁 Creating directory structure...")
    try:
        subprocess.run([
            'ssh', f'{ssh_user}@{ha_host}',
            'mkdir -p /config/automations'
        ], check=True, timeout=30)
        print("✅ Directory structure created")
    except Exception as e:
        print(f"❌ Directory creation failed: {e}")
        return False
    
    # Deploy all individual automation files
    automation_files = glob.glob('individual_automations/**/*.yaml', recursive=True)
    
    if not automation_files:
        print("❌ No automation files found")
        return False
    
    print(f"📝 Found {len(automation_files)} automation files")
    
    deployed_count = 0
    for file_path in automation_files:
        try:
            # Get relative path for deployment
            relative_path = Path(file_path).relative_to('individual_automations')
            deploy_path = f'/config/automations/{relative_path}'
            
            print(f"   Deploying: {file_path} -> {deploy_path}")
            
            # Copy file to Home Assistant
            subprocess.run([
                'scp', file_path, f'{ssh_user}@{ha_host}:{deploy_path}'
            ], check=True, timeout=30)
            
            deployed_count += 1
            
        except Exception as e:
            print(f"   ❌ Failed to deploy {file_path}: {e}")
    
    print(f"✅ Deployed {deployed_count}/{len(automation_files)} automation files")
    
    # Create or update configuration.yaml to include automation directory
    print("⚙️ Updating configuration.yaml...")
    try:
        # Get current configuration
        subprocess.run([
            'scp', f'{ssh_user}@{ha_host}:/config/configuration.yaml', '/tmp/current_config.yaml'
        ], check=True, timeout=30)
        
        # Check if automation directory is already included
        with open('/tmp/current_config.yaml', 'r') as f:
            config_content = f.read()
        
        if 'automation: !include automations/' not in config_content:
            # Add automation directory include
            if 'automation: !include automations.yaml' in config_content:
                # Replace single file include with directory include
                config_content = config_content.replace(
                    'automation: !include automations.yaml',
                    'automation: !include automations/'
                )
            else:
                # Add new automation include
                config_content += '\nautomation: !include automations/\n'
            
            # Write updated configuration
            with open('/tmp/updated_config.yaml', 'w') as f:
                f.write(config_content)
            
            # Deploy updated configuration
            subprocess.run([
                'scp', '/tmp/updated_config.yaml', f'{ssh_user}@{ha_host}:/config/configuration.yaml'
            ], check=True, timeout=30)
            
            print("✅ Configuration updated")
        else:
            print("✅ Configuration already includes automation directory")
        
        # Cleanup
        os.remove('/tmp/current_config.yaml')
        if os.path.exists('/tmp/updated_config.yaml'):
            os.remove('/tmp/updated_config.yaml')
            
    except Exception as e:
        print(f"⚠️  Configuration update failed: {e}")
    
    # Restart Home Assistant
    print("🔄 Restarting Home Assistant...")
    try:
        subprocess.run([
            'ssh', f'{ssh_user}@{ha_host}', 'ha core restart'
        ], check=True, timeout=60)
        print("✅ Home Assistant restart initiated")
    except Exception as e:
        print(f"⚠️  Restart failed: {e}")
    
    print("🎉 Individual automation deployment completed!")
    return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Deploy individual automations to Home Assistant')
    parser.add_argument('--host', default='192.168.86.2', help='Home Assistant hostname')
    parser.add_argument('--ssh-user', default='root', help='SSH username')
    
    args = parser.parse_args()
    
    success = deploy_automations(args.host, args.ssh_user)
    
    if success:
        print("\n✅ All automations deployed successfully!")
        print("🔍 Check your Home Assistant UI to verify the automations are loaded")
    else:
        print("\n❌ Deployment failed")
        exit(1)

if __name__ == '__main__':
    main()
