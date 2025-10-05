#!/usr/bin/env python3
"""
Automated Grafana Dashboard Import Script
Imports the Home Assistant automation dashboard into Grafana
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

class GrafanaDashboardImporter:
    def __init__(self, grafana_url="http://192.168.86.2:3000", grafana_user="admin", grafana_password=None):
        self.grafana_url = grafana_url.rstrip('/')
        self.grafana_user = grafana_user
        self.grafana_password = grafana_password or "admin"  # Default Grafana password
        
        # Try to get credentials from environment
        self.grafana_user = os.getenv("GRAFANA_USER", grafana_user)
        self.grafana_password = os.getenv("GRAFANA_PASSWORD", grafana_password or "admin")
    
    def test_grafana_connection(self):
        """Test if Grafana is accessible"""
        print("🔍 Testing Grafana connection...")
        
        try:
            # Try to access Grafana login page
            req = urllib.request.Request(f"{self.grafana_url}/api/health")
            response = urllib.request.urlopen(req, timeout=10)
            
            if response.status == 200:
                print(f"✅ Grafana is accessible at {self.grafana_url}")
                return True
            else:
                print(f"❌ Grafana returned status {response.status}")
                return False
                
        except urllib.error.URLError as e:
            print(f"❌ Cannot connect to Grafana: {e}")
            return False
        except Exception as e:
            print(f"❌ Error testing Grafana connection: {e}")
            return False
    
    def authenticate_grafana(self):
        """Authenticate with Grafana and get API key"""
        print("🔐 Authenticating with Grafana...")
        
        try:
            # Create authentication request
            auth_data = {
                "user": self.grafana_user,
                "password": self.grafana_password
            }
            
            data = json.dumps(auth_data).encode('utf-8')
            req = urllib.request.Request(
                f"{self.grafana_url}/api/auth/keys",
                data=data,
                headers={"Content-Type": "application/json"}
            )
            
            response = urllib.request.urlopen(req, timeout=10)
            
            if response.status == 200:
                result = json.loads(response.read().decode('utf-8'))
                print("✅ Successfully authenticated with Grafana")
                return result.get('key')
            else:
                print(f"❌ Authentication failed: {response.status}")
                return None
                
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return None
    
    def load_dashboard_json(self, dashboard_file):
        """Load dashboard JSON from file"""
        print(f"📄 Loading dashboard from {dashboard_file}...")
        
        try:
            with open(dashboard_file, 'r') as f:
                dashboard_data = json.load(f)
            
            print("✅ Dashboard JSON loaded successfully")
            return dashboard_data
            
        except FileNotFoundError:
            print(f"❌ Dashboard file not found: {dashboard_file}")
            return None
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in dashboard file: {e}")
            return None
        except Exception as e:
            print(f"❌ Error loading dashboard: {e}")
            return None
    
    def import_dashboard(self, dashboard_data, api_key):
        """Import dashboard into Grafana"""
        print("📊 Importing dashboard into Grafana...")
        
        try:
            # Prepare dashboard data
            dashboard_data["overwrite"] = True  # Overwrite if exists
            dashboard_data["folderId"] = 0  # Import to General folder
            
            # Create import request
            data = json.dumps(dashboard_data).encode('utf-8')
            req = urllib.request.Request(
                f"{self.grafana_url}/api/dashboards/db",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
            )
            
            response = urllib.request.urlopen(req, timeout=30)
            
            if response.status == 200:
                result = json.loads(response.read().decode('utf-8'))
                dashboard_url = f"{self.grafana_url}{result.get('url', '/dashboard/home')}"
                print(f"✅ Dashboard imported successfully!")
                print(f"📊 Dashboard URL: {dashboard_url}")
                return True
            else:
                print(f"❌ Import failed: {response.status}")
                response_text = response.read().decode('utf-8')
                print(f"Error details: {response_text}")
                return False
                
        except Exception as e:
            print(f"❌ Import error: {e}")
            return False
    
    def create_datasource_if_needed(self, api_key):
        """Create InfluxDB datasource if it doesn't exist"""
        print("🔌 Checking for InfluxDB datasource...")
        
        try:
            # Check existing datasources
            req = urllib.request.Request(
                f"{self.grafana_url}/api/datasources",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            
            response = urllib.request.urlopen(req, timeout=10)
            
            if response.status == 200:
                datasources = json.loads(response.read().decode('utf-8'))
                
                # Check if InfluxDB datasource exists
                influxdb_exists = any(ds.get('type') == 'influxdb' for ds in datasources)
                
                if influxdb_exists:
                    print("✅ InfluxDB datasource already exists")
                    return True
                else:
                    print("⚠️  InfluxDB datasource not found")
                    print("   You may need to create it manually in Grafana")
                    print("   Name: 'InfluxDB'")
                    print("   URL: http://a0d7b954-influxdb:8086")
                    print("   Database: homeassistant")
                    return False
            else:
                print(f"❌ Could not check datasources: {response.status}")
                return False
                
        except Exception as e:
            print(f"❌ Error checking datasources: {e}")
            return False
    
    def import_dashboard_from_file(self, dashboard_file):
        """Complete dashboard import process"""
        print("🚀 GRAFANA DASHBOARD IMPORT")
        print("=" * 50)
        
        # Step 1: Test connection
        if not self.test_grafana_connection():
            print("\n❌ Cannot connect to Grafana. Please check:")
            print("   1. Grafana is installed and running")
            print("   2. Grafana is accessible at the configured URL")
            print("   3. Network connectivity is working")
            return False
        
        # Step 2: Authenticate
        api_key = self.authenticate_grafana()
        if not api_key:
            print("\n❌ Authentication failed. Please check:")
            print("   1. Grafana username and password are correct")
            print("   2. Set GRAFANA_USER and GRAFANA_PASSWORD environment variables")
            return False
        
        # Step 3: Load dashboard
        dashboard_data = self.load_dashboard_json(dashboard_file)
        if not dashboard_data:
            return False
        
        # Step 4: Check datasource
        self.create_datasource_if_needed(api_key)
        
        # Step 5: Import dashboard
        success = self.import_dashboard(dashboard_data, api_key)
        
        if success:
            print("\n🎉 DASHBOARD IMPORT COMPLETED!")
            print("=" * 50)
            print("📊 Your Home Assistant automation dashboard is now available in Grafana")
            print(f"🌐 Access Grafana at: {self.grafana_url}")
            print("📈 The dashboard will show automation performance metrics")
            print("\n📋 Next steps:")
            print("   1. Check that InfluxDB datasource is configured")
            print("   2. Verify data is flowing from Home Assistant")
            print("   3. Customize the dashboard as needed")
        
        return success

def main():
    """Main function"""
    print("🏠 Home Assistant Grafana Dashboard Importer")
    print("=" * 60)
    
    # Get configuration
    grafana_url = os.getenv("GRAFANA_URL", "http://192.168.86.2:3000")
    grafana_user = os.getenv("GRAFANA_USER", "admin")
    grafana_password = os.getenv("GRAFANA_PASSWORD")
    
    # Dashboard file path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_file = os.path.join(os.path.dirname(script_dir), "grafana_dashboard.json")
    
    if not os.path.exists(dashboard_file):
        print(f"❌ Dashboard file not found: {dashboard_file}")
        print("   Please ensure grafana_dashboard.json exists in the homeassistant directory")
        sys.exit(1)
    
    # Initialize importer
    importer = GrafanaDashboardImporter(grafana_url, grafana_user, grafana_password)
    
    # Import dashboard
    success = importer.import_dashboard_from_file(dashboard_file)
    
    if success:
        print("\n✅ Dashboard import successful!")
        sys.exit(0)
    else:
        print("\n❌ Dashboard import failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
