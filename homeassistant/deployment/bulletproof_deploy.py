#!/usr/bin/env python3
"""
BULLETPROOF Home Assistant Deployment System
Comprehensive safety system to prevent automation loss
"""

import os
import sys
import subprocess
from datetime import datetime

class BulletproofDeployer:
    def __init__(self):
        self.deployment_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_dir = os.path.dirname(self.deployment_dir)
        
    def run_command(self, command, description=""):
        """Run a command with error handling"""
        if description:
            print(f"🔧 {description}")
        
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.deployment_dir)
            if result.returncode == 0:
                print(f"  ✅ Success")
                if result.stdout.strip():
                    print(f"    Output: {result.stdout.strip()}")
                return True
            else:
                print(f"  ❌ Failed: {result.stderr.strip()}")
                return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False
    
    def deploy_automation_safely(self, automation_file):
        """Deploy a single automation file with full safety checks"""
        print(f"🚀 BULLETPROOF DEPLOYMENT: {automation_file}")
        print("=" * 60)
        
        # Step 1: Validate the automation file
        print("STEP 1: VALIDATION")
        if not self.run_command(f"python3 validate_automations.py '{automation_file}'", 
                               "Validating automation syntax and structure"):
            print("❌ DEPLOYMENT ABORTED: Validation failed")
            return False
        
        # Step 2: Create comprehensive backup
        print("\nSTEP 2: BACKUP")
        if not self.run_command("python3 automation_backup_restore.py backup", 
                               "Creating comprehensive backup"):
            print("❌ DEPLOYMENT ABORTED: Backup failed")
            return False
        
        # Step 3: Safe deployment
        print("\nSTEP 3: SAFE DEPLOYMENT")
        if not self.run_command(f"python3 safe_automation_deploy.py '{automation_file}'", 
                               "Deploying with full safety checks"):
            print("❌ DEPLOYMENT FAILED: Safe deployment failed")
            print("🔄 Automatic rollback should have occurred")
            return False
        
        print("\n🎉 BULLETPROOF DEPLOYMENT COMPLETED SUCCESSFULLY!")
        return True
    
    def restore_from_backup(self, backup_name=None):
        """Restore from a specific backup"""
        print(f"🔄 RESTORING FROM BACKUP: {backup_name or 'latest'}")
        
        if backup_name:
            command = f"python3 automation_backup_restore.py restore '{backup_name}'"
        else:
            # List backups and use the latest
            command = "python3 automation_backup_restore.py restore $(python3 automation_backup_restore.py list | head -1)"
        
        return self.run_command(command, "Restoring from backup")
    
    def list_backups(self):
        """List available backups"""
        return self.run_command("python3 automation_backup_restore.py list", "Listing available backups")
    
    def create_webui_backup(self):
        """Create backup from current web UI state"""
        return self.run_command("python3 automation_backup_restore.py webui", "Creating backup from web UI")
    
    def validate_all_automations(self):
        """Validate all automation files in the project"""
        print("🔍 VALIDATING ALL AUTOMATION FILES")
        
        automations_dir = os.path.join(self.project_dir, "automations")
        if not os.path.exists(automations_dir):
            print("❌ No automations directory found")
            return False
        
        all_valid = True
        for file_name in os.listdir(automations_dir):
            if file_name.endswith('.yaml'):
                file_path = os.path.join(automations_dir, file_name)
                print(f"\n📄 Validating: {file_name}")
                if not self.run_command(f"python3 validate_automations.py '{file_path}'", 
                                       f"Validating {file_name}"):
                    all_valid = False
        
        if all_valid:
            print("\n✅ ALL AUTOMATION FILES ARE VALID")
        else:
            print("\n❌ SOME AUTOMATION FILES HAVE ERRORS")
        
        return all_valid
    
    def emergency_restore(self):
        """Emergency restore procedure"""
        print("🚨 EMERGENCY RESTORE PROCEDURE")
        print("=" * 40)
        
        print("This will restore your Home Assistant to a working state.")
        print("Available options:")
        print("1. List available backups")
        print("2. Restore from specific backup")
        print("3. Create backup from current web UI")
        print("4. Exit")
        
        while True:
            choice = input("\nEnter your choice (1-4): ").strip()
            
            if choice == "1":
                self.list_backups()
            elif choice == "2":
                backup_name = input("Enter backup name: ").strip()
                if backup_name:
                    if self.restore_from_backup(backup_name):
                        print("✅ Emergency restore completed!")
                        break
                    else:
                        print("❌ Emergency restore failed!")
                else:
                    print("❌ No backup name provided")
            elif choice == "3":
                if self.create_webui_backup():
                    print("✅ Web UI backup created!")
                else:
                    print("❌ Web UI backup failed!")
            elif choice == "4":
                print("Exiting emergency restore")
                break
            else:
                print("Invalid choice. Please enter 1-4.")

def main():
    if len(sys.argv) < 2:
        print("BULLETPROOF Home Assistant Deployment System")
        print("=" * 50)
        print("Usage:")
        print("  python3 bulletproof_deploy.py deploy <automation_file>")
        print("  python3 bulletproof_deploy.py restore [backup_name]")
        print("  python3 bulletproof_deploy.py list")
        print("  python3 bulletproof_deploy.py webui")
        print("  python3 bulletproof_deploy.py validate")
        print("  python3 bulletproof_deploy.py emergency")
        print("")
        print("Examples:")
        print("  python3 bulletproof_deploy.py deploy ../automations/my_automation.yaml")
        print("  python3 bulletproof_deploy.py restore automation_backup_20241004_143000")
        print("  python3 bulletproof_deploy.py emergency")
        sys.exit(1)
    
    command = sys.argv[1]
    deployer = BulletproofDeployer()
    
    if command == "deploy":
        if len(sys.argv) < 3:
            print("❌ Please specify automation file to deploy")
            sys.exit(1)
        automation_file = sys.argv[2]
        
        # Convert to absolute path
        if not os.path.isabs(automation_file):
            automation_file = os.path.join(deployer.project_dir, automation_file)
        
        if deployer.deploy_automation_safely(automation_file):
            print("\n🎉 DEPLOYMENT SUCCESSFUL!")
            sys.exit(0)
        else:
            print("\n💥 DEPLOYMENT FAILED!")
            sys.exit(1)
    
    elif command == "restore":
        backup_name = sys.argv[2] if len(sys.argv) > 2 else None
        if deployer.restore_from_backup(backup_name):
            print("\n🎉 RESTORE SUCCESSFUL!")
            sys.exit(0)
        else:
            print("\n💥 RESTORE FAILED!")
            sys.exit(1)
    
    elif command == "list":
        deployer.list_backups()
    
    elif command == "webui":
        if deployer.create_webui_backup():
            print("\n🎉 WEB UI BACKUP CREATED!")
            sys.exit(0)
        else:
            print("\n💥 WEB UI BACKUP FAILED!")
            sys.exit(1)
    
    elif command == "validate":
        if deployer.validate_all_automations():
            print("\n🎉 ALL AUTOMATIONS VALID!")
            sys.exit(0)
        else:
            print("\n💥 SOME AUTOMATIONS INVALID!")
            sys.exit(1)
    
    elif command == "emergency":
        deployer.emergency_restore()
    
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
