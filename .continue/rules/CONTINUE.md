# CONTINUE.md - Homelab Infrastructure Repository

## Project Overview

This repository contains a comprehensive homelab infrastructure setup that combines infrastructure automation, smart home automation, system management tools, and development assistance. It features:

- **Infrastructure as Code** using Terraform for VMware vSphere environments
- **Configuration Management** with Ansible for system automation
- **Smart Home Automation** using Home Assistant
- **Development Tools** including AI-powered development assistance with Continue.dev

## Getting Started

### Prerequisites
- VMware vSphere environment
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
   ./misc\ scripts/bootstrap.sh
   ```

3. Setup AI development assistant (optional):
   ```bash
   ./misc\ scripts/continue-dev/setup-continue-dev.sh
   ```

4. Configure Home Assistant:
   ```bash
   cd homeassistant
   cp ha_config.env.example ha_config.env
   # Edit ha_config.env with your HA credentials
   ./setup_venv.sh
   ```

5. Deploy infrastructure:
   ```bash
   cd terraform
   # Configure terraform.tfvars with your environment details
   terraform init
   terraform plan
   terraform apply
   ```

## Project Structure

### Infrastructure as Code (`terraform/`)
**VMware vSphere Infrastructure Management**
- **Active Directory**: Domain controller and authentication services
- **Tanium**: Endpoint security and management platform
  - Airgap environments for secure deployments
  - QA client environments (versions 7.2, 7.4, 7.6, 7.7)
  - Grafana monitoring integration
- **Consul**: Service discovery and configuration management
- **Vault**: Secrets management and encryption
- **Keycloak**: Identity and access management
- **NSX**: Network virtualization and security
- **vCenter**: VMware vCenter Server management

### Configuration Management (`ansible/`)
**Automated System Configuration**
- **Tanium Client Deployment**: Automated installation across multiple OS types
  - Windows guests
  - Linux distributions (Ubuntu, RHEL, Oracle Linux, CentOS)
  - Version management (3.14 and 3.15 clients)
- **VMware Tools**: Automated VMware tools installation and testing
- **OS-Specific Configurations**: Tailored settings for different operating systems
- **Inventory Management**: vSphere inventory integration

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

### Utility Scripts (`misc scripts/`)

#### System Bootstrap (`bootstrap.sh`)
**Complete Terminal Environment Restoration**
- **Package Management**: Homebrew (macOS), apt (Ubuntu/Debian), dnf/yum (CentOS/RHEL), pacman (Arch)
- **Shell Setup**: zsh, Oh My Zsh, Starship prompt with custom configuration
- **Development Tools**: direnv, htop, jq, fzf, tree, vim, git, curl, wget
- **Cross-Platform**: Automatically detects OS and configures appropriately

#### AI Development Assistant (`continue-dev/`)
**Cursor-like AI Functionality with Continue.dev**
- **Autonomous AI Agent**: Analyze codebases, generate code, debug issues, execute commands
- **Multiple AI Models**: Local (Ollama) and cloud (OpenAI, Anthropic, Google) support
- **Smart Commands**: 12 specialized commands for different development tasks
- **Privacy Options**: Local models for sensitive code without external data transmission
- **Model Recommendations**: AI analyzes tasks and suggests optimal models

#### System Management Scripts
- **VM Management**: `reimport_vms.sh` - VMware VM reimport utilities
- **Binary Patching**: `patch_binary.sh` - Binary modification tools
- **VPN Connectivity**: `yubikey_vpn_connect.sh` - YubiKey VPN connection automation
- **System Shutdown**: `shutdown-amd-vmcl01.ps1` - PowerShell shutdown scripts

#### Tanium Management (`tanium/`)
**Enterprise Security Platform Tools**
- **Client Management**: API interactions, client configuration
- **Security Operations**: TLS testing, alert management, sensor toggling
- **Data Management**: SQL operations, MD5 checksums, metric pushing
- **Automation**: Question loading, action creation, user/group imports
- **Airgap Operations**: Secure deployment scripts for isolated environments

## Development Workflow

### Infrastructure Development
1. Make changes to Terraform configuration files in `terraform/`
2. Run `terraform plan` to preview changes
3. Apply with `terraform apply`

### Configuration Management
1. Modify Ansible playbooks in `ansible/`
2. Run with `ansible-playbook` command
3. Use specific inventory for different environments

### Home Assistant Development
1. Modify YAML files in `homeassistant/`
2. Run `./deploy_homeassistant.sh` to deploy changes
3. Use `./setup_venv.sh` to manage dependencies

### AI Development with Continue
1. Configure `~/.continue/config.yaml`
2. Use custom commands like `/cursor-agent` or `/cloud-architect`
3. Leverage MCP tools for enhanced capabilities

## Key Concepts

### Infrastructure as Code (IaC)
- **Terraform**: Declarative infrastructure management
- **State Management**: Persistent state tracking across environments
- **Modular Design**: Reusable components for different infrastructure elements

### Configuration Management
- **Ansible Playbooks**: Idempotent automation scripts
- **Inventory Management**: Multi-environment targeting
- **Role-Based Deployment**: OS-specific configurations

### Smart Home Architecture
- **Event-Driven Automation**: Sensor-based triggers and actions
- **Safety Mechanisms**: Runtime limits, cooldown periods, manual overrides
- **Home Assistant Integration**: Comprehensive ecosystem support

### AI Development Patterns
- **Hybrid Local/Cloud Models**: Cost-optimized approach using LM Studio and cloud providers
- **Custom Commands**: Specialized AI workflows for different tasks
- **MCP Integration**: Extended capabilities through Model Context Protocol

## Common Tasks

### Deploying Infrastructure
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

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

### AI Development Setup
```bash
# Configure Continue.dev with the local setup
cp "misc scripts/continue-dev/continue-config.yaml" ~/.continue/config.yaml

# Start LM Studio server with Qwen models
# Then in VSCode, use Continue.dev commands
```

## Troubleshooting

### Infrastructure Issues
- Check Terraform state files for consistency
- Validate vSphere connectivity before applying changes
- Review logs in `terraform.tfstate` for errors

### Configuration Issues
- Ensure Ansible inventory is properly configured
- Verify host connectivity before running playbooks
- Check variable files in `ansible/group_vars/`

### Home Assistant Problems
- Validate YAML configuration with `ha core check`
- Restore from backups if deployment fails
- Check logs for automation errors

### AI Development Problems
- Verify LM Studio server is running on port 1234
- Check API keys in `~/.continue/.env`
- Ensure Docker Desktop is running for MCP servers

## References

### Documentation
- **Home Assistant**: `homeassistant/README.md` and `homeassistant/water_heater_pump_README.md`
- **AI Development**: `misc scripts/continue-dev/README.md`
- **Tanium Management**: `misc scripts/tanium/` for various utility scripts
- **System Bootstrap**: `misc scripts/bootstrap.sh` for cross-platform terminal setup

### Technology Stack
- **Infrastructure**: VMware vSphere, Terraform, Ansible, Consul, Vault
- **Smart Home**: Home Assistant, Python, YAML
- **Development**: Continue.dev, Ollama, VS Code, Git
- **System Management**: Bash/Shell Scripting, PowerShell, Python

### Related Resources
- [Tanium Download Performance Analysis Guide](misc scripts/tanium/ANALYZE_TANIUM_PCAPS_README.md)
- [Continue.dev Documentation](https://docs.continue.dev)
- [Home Assistant Configuration Guide](https://www.home-assistant.io/docs/)
