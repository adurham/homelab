# Home Assistant Automation System

A comprehensive Home Assistant automation system with deployment tools, entity management, and monitoring capabilities.

## 📚 **Documentation Index**

### Core Rules and Guidelines
- **[RULES.md](RULES.md)** - Development rules and best practices
- **[ENTITY_RULES.md](ENTITY_RULES.md)** - Entity naming and usage guidelines
- **[DEPLOYMENT_RULES.md](DEPLOYMENT_RULES.md)** - Deployment procedures and safety
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions
- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Quick commands and patterns

### System Components
- **[automations/](automations/)** - Home Assistant automation files
- **[scripts/](scripts/)** - Home Assistant script files
- **[python_scripts/](python_scripts/)** - Python script files
- **[deployment/](deployment/)** - Deployment tools and scripts
- **[entity_inventory/](entity_inventory/)** - Entity management tools
- **[webui_automations/](webui_automations/)** - Web UI automation management

## 🚀 **Quick Start**

### Prerequisites
- Home Assistant running on `192.168.86.2:8123`
- SSH access to Home Assistant box
- Python 3.7+ for deployment scripts

### Initial Setup
1. **Configure API token** in `ha_config.env`
2. **Set up SSH access** following [SSH_SETUP_GUIDE.md](deployment/SSH_SETUP_GUIDE.md)
3. **Deploy system** using `./deployment/safe_deploy.py`

### First Deployment
```bash
# Create backup and deploy
./deployment/safe_deploy.py --backup --validate --test --deploy

# Or quick deployment
./deployment/minimal_deploy.sh --files-only
```

## 🔧 **System Features**

### Core Automations
- **Nightly Reboot** - Automatic reboot at 3 AM with timer preservation
- **Garage Lights** - Multi-door motion-controlled lighting
- **Timer Management** - Pause/resume timers during reboot
- **Pool Control** - Automated pool pump management
- **Lighting Control** - Sunset/sunrise lighting automation

### Management Tools
- **Entity Inventory** - Extract and manage all entities
- **Automation Audit** - Validate automation references
- **Safe Deployment** - Backup and deploy with rollback
- **Individual Automation Management** - Parse and organize automations

### Monitoring and Logging
- **Comprehensive Logging** - All actions logged with context
- **Health Monitoring** - System status and performance tracking
- **Error Handling** - Graceful error handling and recovery
- **Backup System** - Automatic backups before changes

## 📋 **File Structure**

```
homeassistant/
├── README.md                           # This file
├── RULES.md                           # Development rules
├── ENTITY_RULES.md                    # Entity guidelines
├── DEPLOYMENT_RULES.md                # Deployment procedures
├── TROUBLESHOOTING.md                 # Troubleshooting guide
├── QUICK_REFERENCE.md                 # Quick commands
├── cleanup.sh                         # Directory cleanup script
├── ha_config.env                      # API configuration (ignored by git)
├── configuration.yaml                 # Basic configuration
├── configuration_merged.yaml          # Merged configuration
├── automations/                       # Automation files
│   ├── garage_lights_enhanced.yaml
│   ├── nightly_reboot_with_timer_pause.yaml
│   ├── startup_restore_timers.yaml
│   └── test_timer_pause_resume.yaml
├── scripts/                           # Script files
│   ├── pause_all_timers.yaml
│   └── resume_all_timers.yaml
├── python_scripts/                    # Python scripts
│   ├── pause_all_timers_script.py
│   ├── restore_timer_states.py
│   └── store_timer_state.py
├── deployment/                        # Deployment tools
│   ├── README.md
│   ├── SSH_SETUP_GUIDE.md
│   ├── safe_deploy.py
│   ├── minimal_deploy.sh
│   ├── deploy_to_ha.py
│   ├── deploy_homeassistant.yml
│   └── inventory.yml
├── entity_inventory/                  # Entity management
│   ├── README.md
│   ├── extract_with_config.py
│   ├── simple_audit.py
│   ├── fix_automations.py
│   └── garage_lights_final.yaml
└── webui_automations/                 # Web UI management
    ├── README.md
    ├── automations.yaml
    ├── simple_parse.py
    ├── deploy_individual_automations.py
    └── individual_automations/
        ├── lighting/
        ├── pool/
        └── plumbing/
```

## 🚨 **Critical Rules**

### Security
- **NEVER** commit API tokens or passwords
- **ALWAYS** use `ha_config.env` for sensitive data
- **NEVER** hardcode IP addresses in production code
- **ALWAYS** validate entity references before use

### Deployment
- **ALWAYS** create backups before deploying
- **ALWAYS** test changes in safe environment
- **NEVER** deploy during active use without warning
- **ALWAYS** use safe deployment scripts

### Development
- **ALWAYS** include comprehensive logging
- **ALWAYS** use descriptive names and descriptions
- **NEVER** create automations without proper conditions
- **ALWAYS** test edge cases and failure scenarios

## 🔄 **Workflow**

### Making Changes
1. **Read the rules** in [RULES.md](RULES.md)
2. **Create backup** using deployment tools
3. **Make changes** following guidelines
4. **Test thoroughly** in safe environment
5. **Deploy safely** using deployment scripts
6. **Monitor system** for 24 hours
7. **Document changes** and results

### Regular Maintenance
1. **Check logs daily** for errors
2. **Verify automations weekly** for proper function
3. **Clean up monthly** using cleanup script
4. **Update documentation** as needed
5. **Review and improve** processes

## 🆘 **Getting Help**

### Quick Reference
- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Common commands and patterns
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions

### Detailed Information
- **[RULES.md](RULES.md)** - Complete development guidelines
- **[ENTITY_RULES.md](ENTITY_RULES.md)** - Entity management rules
- **[DEPLOYMENT_RULES.md](DEPLOYMENT_RULES.md)** - Deployment procedures

### Emergency Procedures
1. **Check system status**: `ha core info`
2. **View logs**: `ha core logs`
3. **Restore backup**: Use latest backup in `backup/` directory
4. **Restart system**: `ha core restart`
5. **Check documentation**: Review troubleshooting guide

## 📊 **System Status**

### Current Features
- ✅ **Nightly reboot** with timer preservation
- ✅ **Multi-door garage lighting** with motion control
- ✅ **Entity inventory** and audit system
- ✅ **Safe deployment** with backup and rollback
- ✅ **Individual automation** management
- ✅ **Comprehensive logging** and monitoring
- ✅ **Security best practices** implemented

### Monitoring
- **System health**: Checked daily
- **Automation status**: Monitored continuously
- **Entity availability**: Validated regularly
- **Backup integrity**: Verified weekly
- **Documentation**: Updated as needed

## 🎯 **Success Metrics**

### Quality Metrics
- **Zero** hardcoded secrets in code
- **100%** entity validation before use
- **Comprehensive** logging for all actions
- **Clear** error handling for all scenarios

### Performance Metrics
- **Fast** automation execution (< 1 second)
- **Reliable** automation triggers
- **Minimal** false positives
- **Efficient** resource usage

---

**Remember**: This system is designed to be reliable, secure, and maintainable. Follow the rules and guidelines to ensure continued success.