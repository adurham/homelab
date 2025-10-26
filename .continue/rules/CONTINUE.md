# 🏠 Homelab Infrastructure Repository - CONTINUE.md

This guide provides comprehensive documentation for the Homelab Infrastructure Repository, a complete system that includes infrastructure automation, smart home automation, system management, and development tools.

## 🚀 Project Overview

This repository contains a complete homelab infrastructure setup featuring:

- **Infrastructure as Code** using Terraform and VMware vSphere
- **Configuration Management** with Ansible automation
- **Smart Home Automation** powered by Home Assistant
- **System Management** with cross-platform bootstrap scripts
- **Development Tools** including AI-powered development assistance

### Key Technologies Used

- **Infrastructure**: VMware vSphere, Terraform, Consul, Vault, NSX, Keycloak
- **Configuration Management**: Ansible
- **Smart Home**: Home Assistant, Python automation
- **Development Tools**: Continue.dev, Ollama, VS Code
- **System Management**: Bash/Shell scripting, PowerShell, Python

## 📦 Getting Started

### Prerequisites

1. **VMware vSphere Environment** - Required for infrastructure deployment
2. **Home Assistant Instance** - For smart home automation
3. **Python 3.x** - Required for various automation scripts
4. **Git** - Version control system

### Installation Instructions

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd homelab
   ```

2. **Restore Terminal Environment** (Optional)
   ```bash
   ./misc/scripts/bootstrap.sh
   ```

3. **Setup AI Development Assistant** (Optional)
   ```bash
   ./misc/scripts/continue-dev/setup-continue-dev.sh
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

### Basic Usage Examples

- **Infrastructure Deployment**: `cd terraform && terraform apply`
- **System Bootstrap**: `./misc/scripts/bootstrap.sh`
- **Home Assistant Deployment**: `cd homeassistant && ./deploy_homeassistant.sh`
- **Tanium Client Installation**: `ansible-playbook ansible/playbook_install_tanium_client.yml`

## 📁 Project Structure

### Main Directories and Components

1. **`terraform/`** - Infrastructure as Code using Terraform
   - **Active Directory**: Domain controller and authentication services
   - **Tanium**: Endpoint security and management platform with multiple client environments (7.2, 7.4, 7.6, 7.7)
   - **Consul**: Service discovery and configuration management
   - **Vault**: Secrets management and encryption
   - **Keycloak**: Identity and access management
   - **NSX**: Network virtualization and security
   - **vCenter**: VMware vCenter Server management

2. **`ansible/`** - Configuration Management using Ansible
   - **Tanium Client Deployment**: Automated installation across multiple OS types (Windows, Ubuntu, RHEL, Oracle Linux, CentOS)
   - **VMware Tools**: Automated VMware tools installation and testing
   - **OS-Specific Configurations**: Tailored settings for different operating systems
   - **Inventory Management**: vSphere inventory integration

3. **`homeassistant/`** - Smart Home Automation System
   - **Water Heater Circulator Pump System**: Automatic pump control based on occupancy detection
   - **Lighting Automation**: Cat room lighting, front porch sconces, garage lighting, stair lighting
   - **Deployment Safety**: Change detection, automatic backups, validation layers

4. **`misc scripts/`** - Utility Scripts
   - **System Bootstrap**: Complete terminal environment restoration across platforms (macOS, Ubuntu, Debian, CentOS, Arch)
   - **Tanium Management**: API interactions, client configuration, security operations
   - **VM Management**: VMware VM reimport utilities and PowerShell shutdown scripts
   - **AI Development Assistant**: Continue.dev integration with local Ollama models

### Key Files and Their Roles

- **`README.md`** - Main project documentation and overview
- **`terraform/variables.tf`** - Terraform variable definitions for infrastructure deployment
- **`ansible/playbook_install_tanium_client.yml`** - Ansible playbook for Tanium client deployment
- **`homeassistant/automations.yaml`** - Home Assistant automation configurations (UI-managed)
- **`misc/scripts/bootstrap.sh`** - Cross-platform terminal environment restoration

## 🛠️ Development Workflow

### Coding Standards and Conventions

1. **Infrastructure as Code**: 
   - Use Terraform for infrastructure provisioning
   - Follow modular structure with variables and outputs
   - Maintain sensitive data in separate files (not committed to repo)

2. **Configuration Management**:
   - Ansible playbooks follow standard structure
   - Use roles for organizing configuration logic
   - Keep secrets out of version control

3. **Smart Home Automation**:
   - YAML configuration files with proper formatting
   - Python scripts for complex automation logic
   - Automated testing and validation

4. **System Management**:
   - Bash scripts with proper error handling
   - Cross-platform compatibility considerations
   - Shell script best practices (set -euo pipefail)

### Testing Approach

1. **Infrastructure**:
   - Use `terraform plan` to review changes before applying
   - Validate variable files before deployment
   - Test in non-production environments first

2. **Configuration Management**:
   - Run Ansible playbooks with `--check` mode to preview changes
   - Test on individual hosts before large-scale deployment

3. **Home Assistant**:
   - Validate YAML configurations with `yaml` command
   - Use Home Assistant's built-in validation features
   - Deploy changes in safe environments first

### Build and Deployment Process

1. **Infrastructure**:
   - Initialize Terraform: `terraform init`
   - Plan deployment: `terraform plan`
   - Apply configuration: `terraform apply`

2. **Configuration Management**:
   - Run playbooks with: `ansible-playbook <playbook.yml>`
   - Use tags for targeted deployments

3. **Home Assistant**:
   - Deploy configurations with automated scripts
   - Use backup mechanisms during deployments

### Contribution Guidelines

1. **Code Review**: All changes should be reviewed before merging
2. **Documentation**: Update documentation when making significant changes
3. **Testing**: Ensure changes don't break existing functionality
4. **Security**: Never commit sensitive data to version control

## 🔧 Key Concepts

### Domain-Specific Terminology

1. **VMware vSphere**: Virtualization platform for managing virtual machines and resources
2. **Tanium**: Enterprise endpoint security and management platform
3. **NSX**: Network virtualization and security platform 
4. **Consul**: Service discovery and configuration management tool
5. **Vault**: Secrets management and encryption system
6. **Keycloak**: Identity and access management platform
7. **Home Assistant**: Open-source home automation platform

### Core Abstractions

1. **Infrastructure as Code**: 
   - Terraform modules for reusable infrastructure components
   - Variable-based configuration management

2. **Configuration Management**:
   - Ansible roles for organizing system configurations
   - Inventory-based targeting of systems

3. **Smart Home Automation**:
   - Occupancy-based triggers and controls
   - Integration with home automation systems

### Design Patterns Used

1. **Modular Infrastructure**: Terraform modules for components like Tanium clients, Active Directory
2. **Cross-Platform Compatibility**: Bootstrap scripts that work across macOS, Linux distributions, and Windows
3. **Separation of Concerns**: Clear division between infrastructure, configuration, and application layers
4. **Security by Design**: Sensitive data handled through variables and proper file permissions

## 📝 Common Tasks

### Step-by-Step Guides for Frequent Development Tasks

#### 1. Deploying New Infrastructure

1. Modify Terraform configuration files in `terraform/`
2. Update variables in `terraform/variables.tf` or `.tfvars` files
3. Run `terraform init` to initialize the working directory
4. Run `terraform plan` to review changes
5. Run `terraform apply` to deploy the infrastructure

#### 2. Installing Tanium Client on New VMs

1. Tag new VMs in VMware vSphere with appropriate tags
2. Run the Ansible playbook: 
   ```bash
   ansible-playbook ansible/playbook_install_tanium_client.yml
   ```
3. Verify client installation on target systems

#### 3. Restoring Terminal Environment

1. Run the bootstrap script:
   ```bash
   ./misc/scripts/bootstrap.sh
   ```
2. The script will detect your OS and install appropriate packages
3. Configure shell with Oh My Zsh and Starship prompt

#### 4. Updating Home Assistant Configuration

1. Make changes to configuration files in `homeassistant/`
2. Validate configurations with:
   ```bash
   # Use Home Assistant's validation features or YAML linting tools
   ```
3. Deploy changes using the automated deployment scripts

#### 5. Managing Tanium Security Operations

1. Use the Tanium management scripts in `misc/scripts/tanium/`
2. Examples include MD5 index fixing for database security
3. Follow proper authentication procedures for Tanium API access

## 🛠️ Troubleshooting

### Common Issues and Their Solutions

1. **Terraform Configuration Issues**:
   - Error: "Invalid variable value" - Check that all required variables are set in `terraform.tfvars`
   - Error: "Permission denied" - Ensure you have appropriate permissions for vCenter and NSX

2. **Ansible Playbook Failures**:
   - Error: "Host not found" - Verify that VMs are tagged correctly in vSphere inventory
   - Error: "Authentication failed" - Check credentials in Ansible inventory or variables

3. **Home Assistant Deployment Issues**:
   - Error: "Configuration invalid" - Validate YAML with `yaml` command or Home Assistant's config validation
   - Error: "Backup failed" - Ensure backup directory has proper permissions

4. **Bootstrap Script Issues**:
   - Error: "Command not found" - Ensure the script has execute permissions (`chmod +x bootstrap.sh`)
   - Error: "Package manager not found" - Verify that the OS is supported by the bootstrap script

### Debugging Tips

1. **Infrastructure**:
   - Use `terraform show` to view the current state
   - Check logs in VMware vSphere for detailed error information

2. **Configuration Management**:
   - Use `ansible-playbook -vv` for verbose output to debug issues
   - Test individual roles before running full playbooks

3. **Home Assistant**:
   - Check logs in Home Assistant's log viewer
   - Use the "Check Configuration" feature in the UI

## 📚 References

### Important Resources

1. **VMware vSphere Documentation**: https://docs.vmware.com/
2. **Terraform Documentation**: https://www.terraform.io/docs
3. **Ansible Documentation**: https://docs.ansible.com/
4. **Home Assistant Documentation**: https://www.home-assistant.io/docs/

### Related Tools and Services

1. **Continue.dev**: AI-powered development assistant (local model support)
2. **Ollama**: Local AI model hosting for development
3. **Home Assistant**: Open-source home automation platform
4. **Tanium**: Enterprise endpoint security and management platform

### Configuration Files

1. **Terraform Variables**: `terraform/variables.tf`
2. **Home Assistant Environment**: `homeassistant/ha_config.env.example`
3. **Bootstrap Script**: `misc/scripts/bootstrap.sh`

### Security Considerations

- All sensitive credentials are stored as Terraform variables and not committed to the repository
- Tanium API access requires proper authentication and permissions
- Network security is handled through NSX and vCenter configuration

### Platform Support

The bootstrap script supports multiple platforms:
- macOS (Intel and Apple Silicon)
- Ubuntu/Debian-based distributions
- CentOS/RHEL-based distributions
- Arch-based distributions

This documentation provides a foundation for working with the homelab infrastructure repository. For specific technical details, please consult the individual component documentation and configuration files.