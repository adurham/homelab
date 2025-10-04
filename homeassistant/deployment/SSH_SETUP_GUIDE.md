# SSH Setup Guide for Home Assistant Green

This guide will walk you through enabling SSH access to your Home Assistant Green box using only the web UI.

## 📋 Prerequisites

- Access to Home Assistant web UI at `http://homeassistant.local:8123`
- Admin user account in Home Assistant

## 🔧 Step-by-Step SSH Setup

### Step 1: Navigate to Add-ons

1. Open your Home Assistant web UI: `http://homeassistant.local:8123`
2. In the left sidebar, click **Settings**
3. Click **Add-ons**

### Step 2: Install Terminal & SSH Add-on

1. Click **Add-on Store** (if not already selected)
2. In the search box, type: `Terminal & SSH`
3. Look for **"Terminal & SSH"** by **Frenck**
4. Click on the **Terminal & SSH** add-on

### Step 3: Install the Add-on

1. Click the **INSTALL** button
2. Wait for the installation to complete (this may take a few minutes)
3. You'll see a progress bar during installation

### Step 4: Configure the Add-on

1. After installation, click the **Configuration** tab
2. You'll see a configuration editor with JSON content
3. Replace the default configuration with this:

```json
{
  "ssh": {
    "username": "homeassistant",
    "password": "your_secure_password_here",
    "authorized_keys": [],
    "sftp": true,
    "compatibility_mode": false,
    "allow_agent_forwarding": false,
    "allow_remote_port_forwarding": false,
    "allow_tcp_forwarding": false
  },
  "share_sessions": false,
  "packages": [],
  "init_commands": []
}
```

4. **Replace `"your_secure_password_here"`** with a strong password you'll remember
5. Click **SAVE**

### Step 5: Start the Add-on

1. Go to the **Info** tab
2. Click **START**
3. Wait for the add-on to start (status should show "Running")

### Step 6: Verify SSH is Working

1. In the **Info** tab, you should see:
   - Status: **Running**
   - Port: **22**
   - Host: **homeassistant.local** (or your HA IP)

## 🔐 Alternative: SSH Key Authentication (More Secure)

If you want to use SSH keys instead of passwords:

### Generate SSH Key (on your Mac)

```bash
# Generate SSH key pair
ssh-keygen -t rsa -b 4096 -f ~/.ssh/ha_key

# Copy the public key
cat ~/.ssh/ha_key.pub
```

### Configure SSH Key in Home Assistant

1. Copy the public key content (from `~/.ssh/ha_key.pub`)
2. In the Terminal & SSH configuration, replace the config with:

```json
{
  "ssh": {
    "username": "homeassistant",
    "password": "",
    "authorized_keys": [
      "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQD... your_public_key_here"
    ],
    "sftp": true,
    "compatibility_mode": false,
    "allow_agent_forwarding": false,
    "allow_remote_port_forwarding": false,
    "allow_tcp_forwarding": false
  },
  "share_sessions": false,
  "packages": [],
  "init_commands": []
}
```

3. Replace `"your_public_key_here"` with your actual public key
4. Save and restart the add-on

## 🧪 Test SSH Connection

### From Terminal (Password Authentication)

```bash
# Test connection with password
ssh homeassistant@homeassistant.local

# You'll be prompted for the password you set in Step 4
```

### From Terminal (SSH Key Authentication)

```bash
# Test connection with SSH key
ssh -i ~/.ssh/ha_key homeassistant@homeassistant.local

# No password should be required
```

## 🚀 Deploy Your Configurations

Once SSH is working, you can deploy your configurations:

```bash
cd /Users/adam.durham/repos/homelab/homeassistant/deployment

# Test connection first
./deploy.sh --ssh-user homeassistant --test-only

# Deploy everything
./deploy.sh --ssh-user homeassistant
```

## 🔍 Troubleshooting

### SSH Connection Refused

1. **Check if add-on is running**:
   - Go to Settings → Add-ons → Terminal & SSH → Info
   - Status should be "Running"

2. **Check port 22**:
   - The add-on should show Port: 22
   - Try connecting with: `ssh homeassistant@homeassistant.local -p 22`

3. **Try IP address instead**:
   - Find your Home Assistant IP in Settings → System → Network
   - Connect with: `ssh homeassistant@YOUR_HA_IP`

### Authentication Failed

1. **Check username**: Make sure it's "homeassistant"
2. **Check password**: Verify the password in the configuration
3. **Check SSH key**: If using keys, verify the public key is correct

### Add-on Won't Start

1. **Check logs**:
   - Go to Settings → Add-ons → Terminal & SSH → Logs
   - Look for error messages

2. **Check configuration syntax**:
   - Make sure the JSON is valid
   - Use a JSON validator if needed

3. **Restart Home Assistant**:
   - Sometimes a full restart helps

## 📞 Getting Help

If you're still having issues:

1. **Check Home Assistant logs**:
   - Settings → System → Logs
   - Filter by "Terminal & SSH"

2. **Try the web terminal first**:
   - In the Terminal & SSH add-on, click "Open Web UI"
   - This will open a web-based terminal to test

3. **Verify network connectivity**:
   - Make sure your Mac can reach `homeassistant.local`
   - Try pinging: `ping homeassistant.local`

## ✅ Success Indicators

You'll know SSH is working when:

- ✅ Add-on status shows "Running"
- ✅ You can connect with `ssh homeassistant@homeassistant.local`
- ✅ You can run commands like `ha core info`
- ✅ The deployment script connects successfully

Once SSH is working, you'll be able to deploy your Home Assistant configurations automatically!
