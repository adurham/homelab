# CONTINUE.md - Homelab Infrastructure Repository

## Project Overview

This repository contains a comprehensive homelab infrastructure setup that combines infrastructure automation, smart home automation, system management tools, and development assistance. It features:

- **Configuration Management** with Ansible for Proxmox-based infrastructure
- **Smart Home Automation** using Home Assistant

## Getting Started

### Prerequisites
- Home Assistant instance
- Python 3.x
- Git

### Quick Start
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd homelab
   ```

2. Restore terminal environment (optional):
   ```bash
   ./scripts/bootstrap.sh
   ```

3. Configure Home Assistant:
   ```bash
   cd homeassistant
   cp ha_config.env.example ha_config.env
   # Edit ha_config.env with your HA credentials
   ./setup_venv.sh
   ```

## Project Structure

### Configuration Management (`ansible/`)
**Automated System Configuration**
- **Tanium Client Deployment**: Automated installation across multiple OS types
  - Windows guests
  - Linux distributions (Ubuntu, RHEL, Oracle Linux, CentOS)
  - Version management (3.14 and 3.15 clients)
- **OS-Specific Configurations**: Tailored settings for different operating systems
- **Proxmox Inventory**: Inventory sourced from Proxmox

### Smart Home Automation (`homeassistant/`)
**Intelligent Home Control System**

#### Water Heater Circulator Pump System
- **Smart Pump Control**: Automatic water heater circulator pump based on occupancy detection
- **Occupancy Detection**: Monitors kitchen and bathroom occupancy sensors
- **Safety Features**: Daily runtime limits (8 hours max), cooldown periods (45 minutes)
- **Room Coverage**: Kitchen, half bathroom, main bathroom, guest bathroom
- **Automation Logic**: 15-minute pump cycles with intelligent scheduling

#### Lighting Automation
- **Cat Room Lighting**: Automated main lights control
- **Front Porch Sconces**: Motion-activated lighting
- **Garage Lighting**: Door motion control integration
- **Stair Lighting**: Automated on/off control

#### Advanced Features
- **Deployment Safety**: Change detection, automatic backups, validation layers
- **Error Recovery**: Auto-restore from backups if deployment fails
- **Virtual Environment**: Isolated Python dependencies
- **YAML Linting**: Automated configuration validation

### Utility Scripts (`scripts/`)

#### System Bootstrap (`bootstrap.sh`)
**Complete Terminal Environment Restoration**
- **Package Management**: Homebrew (macOS), apt (Ubuntu/Debian), dnf/yum (CentOS/RHEL), pacman (Arch)
- **Shell Setup**: zsh, Oh My Zsh, Starship prompt with custom configuration
- **Development Tools**: direnv, htop, jq, fzf, tree, vim, git, curl, wget
- **Cross-Platform**: Automatically detects OS and configures appropriately

#### System Management Scripts
- **Binary Patching**: `patch_binary.sh` - Binary modification tools
- **VPN Connectivity**: `yubikey_vpn_connect.sh` - YubiKey VPN connection automation

#### Tanium Management (`tanium/`)
**Enterprise Security Platform Tools**
- **Client Management**: API interactions, client configuration
- **Security Operations**: TLS testing, alert management, sensor toggling
- **Data Management**: SQL operations, MD5 checksums, metric pushing
- **Automation**: Question loading, action creation, user/group imports
- **Airgap Operations**: Secure deployment scripts for isolated environments

## Development Workflow

### Configuration Management
1. Modify Ansible playbooks in `ansible/`
2. Run with `ansible-playbook` command
3. Use specific inventory for different environments

### Home Assistant Development
1. Modify YAML files in `homeassistant/`
2. Run `./deploy_homeassistant.sh` to deploy changes
3. Use `./setup_venv.sh` to manage dependencies

## Key Concepts

### Configuration Management
- **Ansible Playbooks**: Idempotent automation scripts
- **Inventory Management**: Multi-environment targeting
- **Role-Based Deployment**: OS-specific configurations

### Smart Home Architecture
- **Event-Driven Automation**: Sensor-based triggers and actions
- **Safety Mechanisms**: Runtime limits, cooldown periods, manual overrides
- **Home Assistant Integration**: Comprehensive ecosystem support

## Common Tasks

### Installing Tanium Clients
```bash
# Run the Tanium client installation playbook
ansible-playbook ansible/playbook_install_tanium_client.yml

# This installs Tanium clients on different OS types:
# - Windows guests
# - Linux distributions (Ubuntu, RHEL, Oracle Linux, CentOS)
```

### Home Assistant Deployment
```bash
cd homeassistant
./deploy_homeassistant.sh
```

## Troubleshooting

### Configuration Issues
- Ensure Ansible inventory is properly configured
- Verify host connectivity before running playbooks
- Check variable files in `ansible/group_vars/`

### Home Assistant Problems
- Validate YAML configuration with `ha core check`
- Restore from backups if deployment fails
- Check logs for automation errors

## References

### Documentation
- **Home Assistant**: `homeassistant/README.md` and `homeassistant/water_heater_pump_README.md`
- **Tanium Management**: `scripts/tanium/` for various utility scripts
- **System Bootstrap**: `scripts/bootstrap.sh` for cross-platform terminal setup

### Technology Stack
- **Infrastructure**: Proxmox VE, Ansible
- **Smart Home**: Home Assistant, Python, YAML
- **Development**: VS Code, Git
- **System Management**: Bash/Shell Scripting, Python

### Related Resources
- [Tanium Download Performance Analysis Guide](scripts/tanium/ANALYZE_TANIUM_PCAPS_README.md)
- [Home Assistant Configuration Guide](https://www.home-assistant.io/docs/)
