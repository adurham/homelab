# 🏠 Homelab Infrastructure Repository

A comprehensive homelab setup featuring infrastructure automation, smart home automation, system management, and development tools.

## 🚀 Quick Start

### System Bootstrap Script

Restore your entire terminal/shell setup from scratch after a system wipe:

```bash
# Run the bootstrap script to restore your terminal setup
./misc\ scripts/bootstrap.sh
```

The bootstrap script supports:

- ✅ **macOS** (Intel and Apple Silicon)
- ✅ **Ubuntu/Debian-based** (Ubuntu, Debian, Pop!_OS, Elementary, Linux Mint)
- ✅ **CentOS/RHEL-based** (CentOS, RHEL, Rocky Linux, AlmaLinux, Fedora)
- ✅ **Arch-based** (Arch Linux, Manjaro)

## 📁 Repository Overview

This repository contains a complete homelab infrastructure setup with the following major components:

### 🏗️ Infrastructure as Code (`terraform/`)

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

### 🤖 Configuration Management (`ansible/`)

**Automated System Configuration**

- **Tanium Client Deployment**: Automated installation across multiple OS types
  - Windows guests
  - Linux distributions (Ubuntu, RHEL, Oracle Linux, CentOS)
  - Version management (3.14 and 3.15 clients)
- **VMware Tools**: Automated VMware tools installation and testing
- **OS-Specific Configurations**: Tailored settings for different operating systems
- **Inventory Management**: vSphere inventory integration

#### 🏃 Runner Setup

To prepare a new machine (CI/CD runner or workstation) with all dependencies:

```bash
./ansible/setup_runner.sh
```

### 🏠 Smart Home Automation (`homeassistant/`)

**Intelligent Home Control System**

#### 🌡️ Water Heater Circulator Pump System

- **Smart Pump Control**: Automatic water heater circulator pump based on occupancy detection
- **Occupancy Detection**: Monitors kitchen and bathroom occupancy sensors
- **Safety Features**: Daily runtime limits (8 hours max), cooldown periods (45 minutes)
- **Room Coverage**: Kitchen, half bathroom, main bathroom, guest bathroom
- **Automation Logic**: 15-minute pump cycles with intelligent scheduling

#### 💡 Lighting Automation

- **Cat Room Lighting**: Automated main lights control
- **Front Porch Sconces**: Motion-activated lighting
- **Garage Lighting**: Door motion control integration
- **Stair Lighting**: Automated on/off control

#### 🔧 Advanced Features

- **Deployment Safety**: Change detection, automatic backups, validation layers
- **Error Recovery**: Auto-restore from backups if deployment fails
- **Virtual Environment**: Isolated Python dependencies
- **YAML Linting**: Automated configuration validation

### 🛠️ Utility Scripts (`misc scripts/`)

#### 🚀 System Bootstrap (`bootstrap.sh`)

**Complete Terminal Environment Restoration**

- **Package Management**: Homebrew (macOS), apt (Ubuntu/Debian), dnf/yum (CentOS/RHEL), pacman (Arch)
- **Shell Setup**: zsh, Oh My Zsh, Starship prompt with custom configuration
- **Development Tools**: direnv, htop, jq, fzf, tree, vim, git, curl, wget
- **Cross-Platform**: Automatically detects OS and configures appropriately

#### 🤖 AI Development Assistant (`continue-dev/`)

**Cursor-like AI Functionality with Continue.dev**

- **Autonomous AI Agent**: Analyze codebases, generate code, debug issues, execute commands
- **Multiple AI Models**: Local (Ollama) and cloud (OpenAI, Anthropic, Google) support
- **Smart Commands**: 12 specialized commands for different development tasks
- **Privacy Options**: Local models for sensitive code without external data transmission
- **Model Recommendations**: AI analyzes tasks and suggests optimal models

#### 🔧 System Management Scripts

- **VM Management**: `reimport_vms.sh` - VMware VM reimport utilities
- **Binary Patching**: `patch_binary.sh` - Binary modification tools
- **VPN Connectivity**: `yubikey_vpn_connect.sh` - YubiKey VPN connection automation
- **System Shutdown**: `shutdown-amd-vmcl01.ps1` - PowerShell shutdown scripts

#### 🔒 Tanium Management (`tanium/`)

**Enterprise Security Platform Tools**

- **Client Management**: API interactions, client configuration
- **Security Operations**: TLS testing, alert management, sensor toggling
- **Data Management**: SQL operations, MD5 checksums, metric pushing
- **Automation**: Question loading, action creation, user/group imports
- **Airgap Operations**: Secure deployment scripts for isolated environments

## 🎯 Key Features

### 🔐 Security & Compliance

- **Tanium Integration**: Enterprise-grade endpoint security
- **Airgap Environments**: Secure deployments for sensitive workloads
- **Vault Integration**: Centralized secrets management
- **Network Security**: NSX-based network virtualization

### 🏠 Smart Home Intelligence

- **Occupancy-Based Automation**: Intelligent pump control based on room usage
- **Safety Mechanisms**: Runtime limits, cooldown periods, manual overrides
- **Comprehensive Monitoring**: Daily statistics, cycle tracking, usage analytics

### 🚀 Development Productivity

- **AI-Powered Development**: Local and cloud AI models for coding assistance
- **Cross-Platform Compatibility**: Works on macOS, Linux, and Windows
- **Automated Setup**: One-command environment restoration
- **Quality Assurance**: Automated testing and validation

### 📊 Monitoring & Observability

- **Grafana Integration**: Comprehensive monitoring dashboards
- **Consul Service Discovery**: Dynamic service registration and health checking
- **Home Assistant Logging**: Detailed automation logging and debugging

## 🛠️ Technology Stack

### Infrastructure

- **VMware vSphere**: Virtualization platform
- **Terraform**: Infrastructure as Code
- **Ansible**: Configuration management
- **Consul**: Service discovery
- **Vault**: Secrets management

### Smart Home

- **Home Assistant**: Open-source home automation platform
- **Python**: Automation scripting and deployment tools
- **YAML**: Configuration management

### Development

- **Continue.dev**: AI-powered development assistant
- **Ollama**: Local AI model hosting
- **VS Code**: Integrated development environment
- **Git**: Version control

### System Management

- **Bash/Shell Scripting**: Automation and system management
- **PowerShell**: Windows system management
- **Python**: Cross-platform scripting and APIs

## 🚀 Getting Started

### Prerequisites

- VMware vSphere environment
- Home Assistant instance
- Python 3.x
- Git

### Initial Setup

1. **Clone the Repository**

   ```bash
   git clone <repository-url>
   cd homelab
   ```

2. **Restore Terminal Environment** (Optional)

   ```bash
   ./misc\ scripts/bootstrap.sh
   ```

3. **Setup AI Development Assistant** (Optional)

   ```bash
   ./misc\ scripts/continue-dev/setup-continue-dev.sh
   ```

4. **Configure Home Assistant**

   ```bash
   cd homeassistant
   cp ha_config.env.example ha_config.env
   # Edit ha_config.env with your HA credentials
   ./setup_venv.sh
   ```

5. **Deploy Infrastructure** (Production)

   ```bash
   cd terraform
   # Configure terraform.tfvars with your environment details
   terraform init
   terraform plan
   terraform apply
   ```

## 📚 Documentation

- **Home Assistant**: See `homeassistant/README.md` and `homeassistant/water_heater_pump_README.md`
- **AI Development**: See `misc scripts/continue-dev/README.md`
- **Tanium Management**: See `misc scripts/tanium/` for various utility scripts
- **System Bootstrap**: See `misc scripts/bootstrap.sh` for cross-platform terminal setup

## 🔧 Maintenance

### Regular Tasks

- **Home Assistant**: Deploy configuration changes with `./homeassistant/deploy_homeassistant.sh`
- **Infrastructure**: Update Terraform configurations as needed
- **Ansible**: Run playbooks for system configuration updates
- **Monitoring**: Check Grafana dashboards and Consul health status

### Backup & Recovery

- **Home Assistant**: Automatic backups created during deployments
- **Infrastructure**: Terraform state files backed up
- **Configuration**: Git repository provides version control

## 🤝 Contributing

This is a personal homelab repository, but the utility scripts and configurations may be useful for others. Feel free to adapt and use the components that fit your needs.

## 📄 License

This repository contains personal homelab configurations and utility scripts. Use at your own discretion and adapt as needed for your environment.
