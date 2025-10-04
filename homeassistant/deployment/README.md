# Home Assistant Configuration Deployment

This directory contains tools for automatically deploying Home Assistant configurations to your Home Assistant Green box.

## 🚀 Quick Start

### Prerequisites

1. **SSH Access** (Recommended):
   - Install the "Terminal & SSH" add-on in Home Assistant
   - Configure SSH access with username/password or SSH keys
   - Ensure the add-on is running

2. **API Access** (Alternative):
   - Generate a Long-Lived Access Token in Home Assistant
   - Go to your profile → Long-Lived Access Tokens → Create Token

3. **Ansible** (Optional):
   - Install Ansible: `pip install ansible`
   - Configure SSH access as above

### Deploy Configurations

Choose one of these methods:

#### Method 1: Simple Shell Script (Recommended)

```bash
# Deploy via SSH
./deploy.sh --ssh-user root

# Deploy via API
./deploy.sh --token your_long_lived_token

# Test connection only
./deploy.sh --ssh-user root --test-only
```

#### Method 2: Python Script

```bash
# Install dependencies
pip install -r requirements.txt

# Deploy via SSH
python3 deploy_to_ha.py --ssh-user root

# Deploy via API
python3 deploy_to_ha.py --token your_token --ha-url http://homeassistant.local:8123
```

#### Method 3: Ansible Playbook

```bash
# Install Ansible
pip install ansible

# Deploy
ansible-playbook -i inventory.yml deploy_homeassistant.yml
```

## 📁 File Structure

```
deployment/
├── deploy.sh                    # Simple deployment script
├── deploy_to_ha.py             # Python deployment script
├── deploy_homeassistant.yml    # Ansible playbook
├── inventory.yml               # Ansible inventory
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## 🔧 Configuration

### SSH Setup

1. **Enable SSH Add-on**:
   - Go to Settings → Add-ons → Add-on Store
   - Search for "Terminal & SSH" and install
   - Configure with username/password or SSH keys
   - Start the add-on

2. **Test SSH Connection**:
   ```bash
   ssh root@homeassistant.local
   ```

### API Setup

1. **Generate Token**:
   - Go to your profile in Home Assistant
   - Scroll to "Long-Lived Access Tokens"
   - Click "Create Token"
   - Copy the generated token

2. **Test API Access**:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
        http://homeassistant.local:8123/api/
   ```

## 🚀 Deployment Methods

### SSH Deployment (Recommended)

**Pros:**
- Most reliable for file transfers
- Works with any Home Assistant setup
- No additional configuration needed

**Cons:**
- Requires SSH add-on to be installed
- Need to manage SSH credentials

**Usage:**
```bash
./deploy.sh --ssh-user root
```

### API Deployment

**Pros:**
- No SSH setup required
- Can trigger additional actions
- More integrated with Home Assistant

**Cons:**
- Limited file upload capabilities
- Requires API token management
- May not work for all file types

**Usage:**
```bash
./deploy.sh --token your_long_lived_token
```

### Ansible Deployment

**Pros:**
- Most robust and configurable
- Built-in error handling and retries
- Can handle complex deployment scenarios
- Idempotent operations

**Cons:**
- Requires Ansible installation
- More complex setup

**Usage:**
```bash
ansible-playbook -i inventory.yml deploy_homeassistant.yml
```

## 🔍 Troubleshooting

### Connection Issues

**SSH Connection Failed:**
```bash
# Test SSH connectivity
ssh -v root@homeassistant.local

# Check if SSH add-on is running
# Go to Settings → Add-ons → Terminal & SSH → Info
```

**API Connection Failed:**
```bash
# Test API connectivity
curl -v http://homeassistant.local:8123/api/

# Verify token is correct
curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://homeassistant.local:8123/api/
```

### Deployment Issues

**Files Not Deployed:**
- Check file permissions
- Verify source directory structure
- Check Home Assistant logs

**Home Assistant Won't Restart:**
- Check configuration syntax
- Verify all required files are present
- Check Home Assistant logs

**Automations Not Working:**
- Verify automations are enabled in UI
- Check Python scripts are in correct location
- Verify configuration.yaml includes required sections

### Logs and Debugging

**Check Home Assistant Logs:**
- Go to Settings → System → Logs
- Filter by "Nightly Reboot" or "Timer"

**Enable Debug Logging:**
Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    homeassistant.components.automation: debug
    homeassistant.components.script: debug
```

## 🔒 Security Considerations

1. **SSH Security:**
   - Use SSH keys instead of passwords
   - Restrict SSH access to specific IPs
   - Regularly rotate SSH keys

2. **API Security:**
   - Keep API tokens secure
   - Use long-lived tokens sparingly
   - Regularly rotate tokens

3. **File Permissions:**
   - Ensure proper file permissions
   - Don't store sensitive data in config files
   - Use environment variables for secrets

## 📋 Maintenance

### Regular Tasks

1. **Test Deployments:**
   ```bash
   ./deploy.sh --ssh-user root --test-only
   ```

2. **Backup Configurations:**
   ```bash
   # Backup before deployment
   cp -r /config /config.backup.$(date +%Y%m%d)
   ```

3. **Monitor Logs:**
   - Check Home Assistant logs regularly
   - Monitor automation execution
   - Verify timer functionality

### Updates

1. **Update Deployment Scripts:**
   ```bash
   git pull origin main
   ./deploy.sh --ssh-user root
   ```

2. **Update Dependencies:**
   ```bash
   pip install -r requirements.txt --upgrade
   ```

## 🆘 Support

If you encounter issues:

1. Check the troubleshooting section above
2. Verify all prerequisites are met
3. Test individual components manually
4. Check Home Assistant logs
5. Verify file permissions and locations

For additional help, check the main Home Assistant documentation or community forums.
