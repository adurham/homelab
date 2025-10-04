# Home Assistant Development Rules

## 🚨 **CRITICAL RULES - NEVER BREAK THESE**

### Security Rules
- **NEVER** commit API tokens, passwords, or secrets to git
- **ALWAYS** use `ha_config.env` for sensitive configuration
- **NEVER** hardcode IP addresses in production code
- **ALWAYS** use placeholder values in templates
- **NEVER** commit generated files (entity inventories, audit reports)

### Deployment Rules
- **ALWAYS** create backups before deploying changes
- **ALWAYS** test automations in a safe environment first
- **NEVER** deploy during active use without warning
- **ALWAYS** use the safe deployment scripts
- **NEVER** manually edit files on the Home Assistant box

### Automation Rules
- **ALWAYS** include comprehensive logging
- **ALWAYS** use descriptive names and descriptions
- **NEVER** create automations without proper conditions
- **ALWAYS** test edge cases and failure scenarios
- **NEVER** use hardcoded entity IDs without validation

## 📋 **DEVELOPMENT GUIDELINES**

### File Organization
- **Automations**: Place in `automations/` directory
- **Scripts**: Place in `scripts/` directory  
- **Python Scripts**: Place in `python_scripts/` directory
- **Documentation**: Place in appropriate `README.md` files
- **Templates**: Use descriptive names with version suffixes

### Naming Conventions
- **Automations**: Use descriptive names with underscores
  - ✅ `garage_lights_motion_control.yaml`
  - ❌ `garage.yaml`
- **Variables**: Use snake_case
  - ✅ `garage_door_state`
  - ❌ `garageDoorState`
- **Entity IDs**: Use consistent prefixes
  - ✅ `switch.garage_main_lights`
  - ❌ `switch.garageLights`

### Code Quality
- **ALWAYS** include comments for complex logic
- **ALWAYS** use consistent indentation (2 spaces)
- **ALWAYS** validate entity existence before use
- **ALWAYS** handle error conditions gracefully
- **ALWAYS** use meaningful log messages

## 🔧 **AUTOMATION PATTERNS**

### Standard Automation Structure
```yaml
- id: 'descriptive_automation_id'
  alias: 'Human Readable Name'
  description: 'What this automation does and why'
  triggers:
    # List all triggers
  conditions:
    # List all conditions
  action:
    # List all actions
  mode: single  # or restart, queued, parallel
```

### Logging Pattern
```yaml
- service: system_log.write
  data:
    message: 'Descriptive log message with context'
    level: info  # or warning, error
```

### Error Handling Pattern
```yaml
- choose:
  - conditions:
      - condition: state
        entity_id: sensor.example
        state: 'on'
    sequence:
      - service: script.handle_success
  - conditions:
      - condition: state
        entity_id: sensor.example
        state: 'off'
    sequence:
      - service: script.handle_error
```

## 🚫 **FORBIDDEN PATTERNS**

### Never Do These
- ❌ **Hardcoded values** in production code
- ❌ **Empty conditions** without proper logic
- ❌ **Infinite loops** or recursive calls
- ❌ **Unvalidated entity references**
- ❌ **Silent failures** without logging
- ❌ **Magic numbers** without explanation
- ❌ **Duplicate code** without abstraction

### Anti-Patterns
- ❌ **God automations** (doing too many things)
- ❌ **Tight coupling** between automations
- ❌ **Hardcoded schedules** without flexibility
- ❌ **Missing error handling**
- ❌ **Unclear naming**

## 📝 **DOCUMENTATION REQUIREMENTS**

### Every File Must Have
- **Purpose**: What it does
- **Dependencies**: What it requires
- **Usage**: How to use it
- **Configuration**: How to configure it
- **Troubleshooting**: Common issues and solutions

### README Structure
```markdown
# Component Name

## Purpose
Brief description of what this component does.

## Dependencies
- List of required entities
- List of required integrations
- List of required scripts

## Usage
How to use this component.

## Configuration
How to configure this component.

## Troubleshooting
Common issues and solutions.

## Examples
Code examples and use cases.
```

## 🔄 **DEPLOYMENT WORKFLOW**

### Before Deploying
1. **Test locally** with safe values
2. **Create backup** of current configuration
3. **Validate** all entity references
4. **Check logs** for any errors
5. **Document changes** in commit message

### During Deployment
1. **Use safe deployment scripts**
2. **Monitor logs** during deployment
3. **Test critical functions** after deployment
4. **Verify** all automations are working
5. **Clean up** any temporary files

### After Deployment
1. **Monitor system** for 24 hours
2. **Check logs** for any issues
3. **Test edge cases** and failure scenarios
4. **Document** any issues found
5. **Update documentation** if needed

## 🚨 **EMERGENCY PROCEDURES**

### If Something Breaks
1. **Stop** the problematic automation
2. **Restore** from backup if necessary
3. **Check logs** for error details
4. **Fix** the issue in development
5. **Test** thoroughly before redeploying
6. **Document** the issue and solution

### Rollback Procedure
1. **Stop** all automations
2. **Restore** configuration from backup
3. **Restart** Home Assistant
4. **Verify** system is working
5. **Investigate** what went wrong
6. **Fix** and test before redeploying

## 📊 **MONITORING REQUIREMENTS**

### Log Monitoring
- **Check logs** daily for errors
- **Monitor** automation execution
- **Track** performance metrics
- **Alert** on critical failures

### Health Checks
- **Verify** all automations are enabled
- **Check** entity availability
- **Test** critical functions
- **Validate** configuration integrity

## 🎯 **SUCCESS METRICS**

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

**Remember**: These rules exist to keep your Home Assistant system stable, secure, and maintainable. When in doubt, ask for clarification rather than guessing.
