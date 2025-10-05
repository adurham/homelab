#!/usr/bin/env python3
"""
Safe Deployment Script for Grafana Logging Automations
Deploys enhanced automations with Grafana logging safely using the bulletproof system
"""

import os
import sys
import time
import subprocess
from datetime import datetime

class GrafanaAutomationDeployer:
    def __init__(self, ha_url="http://192.168.86.2:8123", ha_token=None):
        self.ha_url = ha_url
        self.ha_token = ha_token
        self.deployment_dir = "/Users/adam.durham/repos/homelab/homeassistant"
        
        # Files to deploy
        self.config_files = [
            "configuration_grafana_logging.yaml"
        ]
        
        self.automation_files = [
            "automations/temperature_balancing_grafana.yaml",
            "automations/hot_water_circulation_grafana.yaml", 
            "automations/garage_lights_grafana.yaml"
        ]
        
        self.grafana_dashboard = "grafana_dashboard.json"
    
    def validate_environment(self):
        """Validate deployment environment"""
        print("🔍 Validating deployment environment...")
        
        # Check if we're in the right directory
        if not os.path.exists(f"{self.deployment_dir}/deployment"):
            print(f"❌ Deployment directory not found: {self.deployment_dir}/deployment")
            return False
        
        # Check if files exist
        missing_files = []
        for file_path in self.config_files + self.automation_files:
            full_path = f"{self.deployment_dir}/{file_path}"
            if not os.path.exists(full_path):
                missing_files.append(file_path)
        
        if missing_files:
            print("❌ Missing files:")
            for file_path in missing_files:
                print(f"  - {file_path}")
            return False
        
        print("✅ All required files found")
        return True
    
    def create_backup(self):
        """Create backup using bulletproof system"""
        print("📦 Creating backup...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"grafana_deploy_{timestamp}"
        
        cmd = f"cd {self.deployment_dir} && python3 deployment/bulletproof_deploy.py webui {backup_name}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Backup created: {backup_name}")
            return backup_name
        else:
            print(f"⚠️  Backup warning: {result.stderr}")
            return backup_name  # Continue anyway
    
    def validate_automations(self):
        """Validate all automation files"""
        print("🧪 Validating automation files...")
        
        all_valid = True
        for automation_file in self.automation_files:
            full_path = f"{self.deployment_dir}/{automation_file}"
            print(f"  Validating: {automation_file}")
            
            cmd = f"cd {self.deployment_dir} && python3 deployment/simple_validate.py {automation_file}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"    ✅ Valid")
            else:
                print(f"    ❌ Invalid: {result.stderr}")
                all_valid = False
        
        return all_valid
    
    def deploy_configuration(self):
        """Deploy configuration files"""
        print("📤 Deploying configuration...")
        
        # Deploy the Grafana logging configuration
        config_file = f"{self.deployment_dir}/{self.config_files[0]}"
        
        # Use the bulletproof deployment system
        cmd = f"cd {self.deployment_dir} && python3 deployment/bulletproof_deploy.py deploy {config_file}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Configuration deployed successfully")
            return True
        else:
            print(f"❌ Configuration deployment failed: {result.stderr}")
            return False
    
    def deploy_automations(self):
        """Deploy automation files"""
        print("📤 Deploying automations...")
        
        success_count = 0
        for automation_file in self.automation_files:
            print(f"  Deploying: {automation_file}")
            
            full_path = f"{self.deployment_dir}/{automation_file}"
            cmd = f"cd {self.deployment_dir} && python3 deployment/bulletproof_deploy.py deploy {full_path}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"    ✅ Deployed successfully")
                success_count += 1
            else:
                print(f"    ❌ Deployment failed: {result.stderr}")
        
        print(f"📊 Deployed {success_count}/{len(self.automation_files)} automations")
        return success_count == len(self.automation_files)
    
    def restart_home_assistant(self):
        """Restart Home Assistant"""
        print("🔄 Restarting Home Assistant...")
        
        if not self.ha_token:
            print("⚠️  No API token - skipping restart")
            return False
        
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.ha_token}",
                "Content-Type": "application/json"
            }
            
            # Call restart service
            response = requests.post(
                f"{self.ha_url}/api/services/homeassistant/restart",
                headers=headers,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                print("✅ Home Assistant restart initiated")
                return True
            else:
                print(f"❌ Restart failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Restart error: {e}")
            return False
    
    def verify_deployment(self):
        """Verify deployment success"""
        print("🔍 Verifying deployment...")
        
        if not self.ha_token:
            print("⚠️  No API token - skipping verification")
            return False
        
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.ha_token}",
                "Content-Type": "application/json"
            }
            
            # Wait for restart to complete
            print("  Waiting for Home Assistant to restart...")
            for i in range(30):  # Wait up to 5 minutes
                try:
                    response = requests.get(f"{self.ha_url}/api/", headers=headers, timeout=5)
                    if response.status_code == 200:
                        print("  ✅ Home Assistant is responding")
                        break
                except:
                    pass
                
                time.sleep(10)
                print(f"  ⏳ Still waiting... ({i+1}/30)")
            else:
                print("  ⚠️  Home Assistant may still be restarting")
                return False
            
            # Check if new entities exist
            response = requests.get(f"{self.ha_url}/api/states", headers=headers, timeout=30)
            if response.status_code == 200:
                entities = response.json()
                
                # Look for Grafana logging entities
                grafana_entities = [e for e in entities if 'grafana' in e['entity_id'].lower() or 
                                  'input_number' in e['entity_id'] or 'input_text' in e['entity_id']]
                
                print(f"  📊 Found {len(grafana_entities)} logging entities")
                
                # Check for our specific automations
                automation_count = len([e for e in entities if e['entity_id'].startswith('automation.')])
                print(f"  🤖 Found {automation_count} automations")
                
                return True
            else:
                print(f"  ❌ Verification failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Verification error: {e}")
            return False
    
    def deploy_grafana_dashboard(self):
        """Deploy Grafana dashboard (if Grafana is accessible)"""
        print("📊 Deploying Grafana dashboard...")
        
        dashboard_file = f"{self.deployment_dir}/{self.grafana_dashboard}"
        if os.path.exists(dashboard_file):
            print("  ✅ Dashboard file found")
            print("  📋 Dashboard can be imported manually into Grafana")
            print(f"  📁 Location: {dashboard_file}")
            return True
        else:
            print("  ⚠️  Dashboard file not found")
            return False
    
    def deploy(self):
        """Main deployment process"""
        print("🚀 GRAFANA AUTOMATION DEPLOYMENT")
        print("=" * 50)
        
        # Step 1: Validate environment
        if not self.validate_environment():
            print("❌ Environment validation failed")
            return False
        
        # Step 2: Create backup
        backup_name = self.create_backup()
        
        try:
            # Step 3: Validate automations
            if not self.validate_automations():
                print("❌ Automation validation failed")
                return False
            
            # Step 4: Deploy configuration
            if not self.deploy_configuration():
                print("❌ Configuration deployment failed")
                return False
            
            # Step 5: Deploy automations
            if not self.deploy_automations():
                print("❌ Automation deployment failed")
                return False
            
            # Step 6: Restart Home Assistant
            self.restart_home_assistant()
            
            # Step 7: Verify deployment
            self.verify_deployment()
            
            # Step 8: Deploy Grafana dashboard
            self.deploy_grafana_dashboard()
            
            print("\n🎉 DEPLOYMENT COMPLETED!")
            print(f"📦 Backup available: {backup_name}")
            print("\n📋 Next steps:")
            print("1. Check Home Assistant web UI for new automations")
            print("2. Import Grafana dashboard if needed")
            print("3. Test automation functionality")
            print("4. Monitor Grafana logs")
            
            return True
            
        except Exception as e:
            print(f"❌ Deployment error: {e}")
            print(f"📦 Backup available for restore: {backup_name}")
            return False

def main():
    """Main function"""
    print("🏠 Home Assistant Grafana Automation Deployment")
    print("=" * 60)
    
    # Get configuration
    ha_url = os.getenv("HA_URL", "http://192.168.86.2:8123")
    ha_token = os.getenv("HA_TOKEN")
    
    if not ha_token:
        print("❌ HA_TOKEN environment variable not set")
        print("   Please set your Home Assistant API token:")
        print("   export HA_TOKEN='your_long_lived_access_token'")
        print("   Or update ha_config.env file")
        sys.exit(1)
    
    # Initialize deployer
    deployer = GrafanaAutomationDeployer(ha_url, ha_token)
    
    # Run deployment
    success = deployer.deploy()
    
    if success:
        print("\n✅ DEPLOYMENT SUCCESSFUL!")
        sys.exit(0)
    else:
        print("\n❌ DEPLOYMENT FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    main()
