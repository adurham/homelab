# Home Assistant Development Rules

## 🔧 Development Environment

### Primary Access Method
- **Home Assistant REST API**: Primary method for interacting with Home Assistant
- **URL**: `http://homeassistant.local:8123`
- **Authentication**: Long-lived access tokens via `ha_config.env`

### Secondary Access Method
- **SSH Access**: Secondary method for file operations and CLI commands
- **Host**: `root@homeassistant.local`
- **Port**: `2222`

### Configuration Files
- **Local files**: Development and testing
- **Remote files**: Active Home Assistant configuration
- **Deployment**: Use `./deploy_homeassistant.sh` to sync local → remote

## 📁 File Structure Rules

### Automation Organization
- **UI-managed automations**: `automations.yaml` (managed by Home Assistant UI, do not edit manually)
- **Custom automations**: `automations/<automation>.yaml` (individual files in automations/ directory)
- **Include configuration**: `configuration.yaml` uses both:
  ```yaml
  automation: !include automations.yaml                    # UI-managed
  automation custom: !include_dir_merge_list automations/  # Custom files
  ```
- **No subdirectories**: `!include_dir_merge_list` does NOT support subdirectories - files must be directly in the specified directory

### Script Organization
- **UI-managed scripts**: `scripts.yaml` (managed by Home Assistant UI, do not edit manually)
- **Custom scripts**: `scripts/<system>/<script>.yaml` (individual files in scripts/ directory)
- **Include configuration**: `configuration.yaml` uses both:
  ```yaml
  script: !include scripts.yaml                    # UI-managed
  script custom: !include_dir_merge_list scripts/  # Custom files
  ```

### Scene Organization
- **UI-managed scenes**: `scenes.yaml` (managed by Home Assistant UI, do not edit manually)
- **Custom scenes**: `scenes/<scene>.yaml` (individual files in scenes/ directory)
- **Include configuration**: `configuration.yaml` uses both:
  ```yaml
  scene: !include scenes.yaml                    # UI-managed
  scene custom: !include_dir_merge_list scenes/  # Custom files
  ```

### Helper Entities Organization
- **Helper entities**: Must be defined directly in `configuration.yaml`
- **No custom includes**: Home Assistant does NOT support `input_boolean custom:` syntax
- **Direct definition**: All helper entities go directly under their domain in `configuration.yaml`:
  ```yaml
  input_boolean:
    entity_name:
      name: "Entity Name"
      icon: mdi:icon-name
  input_number:
    entity_name:
      name: "Entity Name"
      min: 0
      max: 100
  counter:
    entity_name:
      name: "Entity Name"
      initial: 0
  timer:
    entity_name:
      name: "Entity Name"
      duration: "00:15:00"
  ```

### Naming Conventions
- **Files**: Use snake_case for YAML files
- **Directories**: Use snake_case for system directories
- **IDs**: Use descriptive IDs in automations and scripts

## 🛡️ Security Rules

### Sensitive Information
- **Never commit**: `ha_config.env` (contains API tokens)
- **Always use**: `ha_config.env.example` as template
- **Gitignore**: Virtual environment, logs, backup files

### Deployment Safety
- **Always backup**: Before any deployment
- **Validate locally**: Run yamllint before deployment
- **Validate remotely**: Run ha core check after deployment
- **Auto-restore**: If validation fails, restore from backup

## 🔄 Development Workflow

### 1. Local Development
```bash
# Setup environment
./setup_venv.sh

# Edit files in automations/ or scripts/
# Test locally with yamllint
./venv/bin/yamllint .
```

### 2. Deployment
```bash
# Deploy to Home Assistant (normal deployment)
./deploy_homeassistant.sh

# Deploy during development (skip safety checks)
./deploy_homeassistant.sh --skip-config-check --skip-ha-backup

# Deploy with custom backup timeout
./deploy_homeassistant.sh --backup-timeout 600
```

### Important Configuration Notes
- **UI-managed files**: `automations.yaml`, `scripts.yaml`, `scenes.yaml` - do not edit manually
- **Custom files**: Use `custom:` includes for automations, scripts, and scenes
- **Helper entities**: Must be defined directly in `configuration.yaml` (no custom includes supported)
- **No subdirectories**: Home Assistant include directives do not support nested subdirectories
- **Deployment script**: Use `--skip-config-check` flag during development to bypass safety checks
```

### 3. Testing
```bash
# Test via API
curl -H "Authorization: Bearer $HA_TOKEN" \
     "http://homeassistant.local:8123/api/states"

# Test via SSH
ssh -p 2222 root@homeassistant.local "ha core check"
```

## 📋 Automation Rules

### Trigger Patterns
- **State changes**: Use for occupancy, temperature, etc.
- **Time patterns**: Use for periodic checks
- **Events**: Use for manual triggers

### Action Patterns
- **Logging**: Always log important actions
- **Error handling**: Use try/catch patterns
- **Variables**: Use for complex calculations

### Script Patterns
- **Parameters**: Use fields for script parameters
- **Validation**: Validate inputs before processing
- **Logging**: Log start/end of script execution

## 🏠 Current Systems

### Vent Control System
- **Purpose**: Intelligent vent control based on occupancy and temperature
- **Logic**: Occupied rooms get priority, unoccupied rooms can drift ±3°F
- **Rooms**: 8 rooms with 10 total vents
- **Automation**: Smart triggers on occupancy, temperature, and periodic checks
- **Scripts**: Orchestration script + individual room control script

## 🚨 Error Handling Rules

### Deployment Errors
- **Local validation fails**: Fix YAML issues before deployment
- **Remote validation fails**: Automatically restore from backup
- **SSH connection fails**: Check network and credentials
- **HA restart fails**: Check logs and restore if needed

### Runtime Errors
- **Automation fails**: Check entity IDs and conditions
- **Script fails**: Check parameters and logic
- **API errors**: Check authentication and network

## 📚 Documentation Rules

### README Files
- **System level**: Explain purpose and usage
- **File level**: Explain parameters and logic
- **Code level**: Inline comments for complex logic

### Code Comments
- **YAML files**: Use `#` for comments
- **Scripts**: Explain complex logic
- **Automations**: Explain trigger conditions

## 🔧 Maintenance Rules

### Regular Tasks
- **Backup rotation**: Automatic via deployment script
- **Dependency updates**: Update requirements.txt
- **Documentation**: Keep README files current
- **Testing**: Test after any changes

### Version Control
- **Commit messages**: Use descriptive messages
- **Branch strategy**: Use feature branches for new systems
- **Review process**: Review before merging to main

## 🚀 Deployment Rules

### Pre-Deployment
1. **Validate locally**: Run yamllint
2. **Check changes**: Verify no external modifications
3. **Create backup**: Always backup before deployment

### Post-Deployment
1. **Validate remotely**: Run ha core check
2. **Test functionality**: Verify automations work
3. **Monitor logs**: Check for errors

### Rollback
1. **Automatic**: Deployment script handles this
2. **Manual**: Use HA CLI backup restore
3. **File restore**: Use file backups if needed
