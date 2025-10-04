# Home Assistant Troubleshooting Guide

## 🚨 **EMERGENCY PROCEDURES**

### System Won't Start
1. **Check logs**: `ha core logs`
2. **Check configuration**: `ha core check`
3. **Restore backup**: Restore from latest backup
4. **Check disk space**: `df -h`
5. **Check memory**: `free -h`

### All Automations Stopped Working
1. **Check automation state**: `ha automation list`
2. **Check logs**: `ha core logs`
3. **Restart automations**: `ha automation reload`
4. **Check entity availability**: `ha states list`
5. **Restart Home Assistant**: `ha core restart`

### Critical Entity Unavailable
1. **Check entity state**: `ha states get <entity_id>`
2. **Check device connectivity**: Check physical device
3. **Restart integration**: `ha integration reload <integration>`
4. **Check logs**: Look for integration errors
5. **Restart Home Assistant**: `ha core restart`

## 🔍 **COMMON ISSUES**

### Automation Issues

#### Automation Not Triggering
**Symptoms**: Automation doesn't run when expected
**Causes**:
- Entity not available
- Condition not met
- Trigger not configured correctly
- Automation disabled

**Solutions**:
1. Check entity availability: `ha states get <entity_id>`
2. Verify trigger configuration
3. Check automation state: `ha automation list`
4. Enable automation: `ha automation enable <automation_id>`
5. Check logs for errors

#### Automation Running Too Often
**Symptoms**: Automation runs repeatedly
**Causes**:
- Missing conditions
- Wrong trigger configuration
- Entity state changes rapidly

**Solutions**:
1. Add proper conditions
2. Use `for` clause in triggers
3. Add debounce logic
4. Check entity state stability

#### Automation Not Completing
**Symptoms**: Automation starts but doesn't finish
**Causes**:
- Service call fails
- Entity not responding
- Timeout issues

**Solutions**:
1. Check service availability
2. Verify entity state
3. Add error handling
4. Check logs for errors

### Entity Issues

#### Entity Shows as Unavailable
**Symptoms**: Entity state is 'unavailable'
**Causes**:
- Device disconnected
- Integration error
- Network issues
- Configuration error

**Solutions**:
1. Check device connectivity
2. Restart integration: `ha integration reload <integration>`
3. Check network connection
4. Verify configuration
5. Restart Home Assistant

#### Entity State Not Updating
**Symptoms**: Entity state doesn't change
**Causes**:
- Device not responding
- Integration issue
- Polling disabled
- Network timeout

**Solutions**:
1. Check device status
2. Restart integration
3. Check polling settings
4. Verify network connection
5. Check logs for errors

#### Entity Has Wrong State
**Symptoms**: Entity shows incorrect state
**Causes**:
- Device malfunction
- Integration bug
- Configuration error
- State sync issue

**Solutions**:
1. Check device physically
2. Restart integration
3. Verify configuration
4. Force state refresh
5. Check logs for errors

### Deployment Issues

#### Deployment Fails
**Symptoms**: Files not deployed correctly
**Causes**:
- SSH connection issues
- Permission problems
- File transfer errors
- Home Assistant not responding

**Solutions**:
1. Check SSH connection: `ssh root@192.168.86.2`
2. Check file permissions
3. Verify Home Assistant status
4. Check disk space
5. Retry deployment

#### Configuration Error After Deployment
**Symptoms**: Home Assistant won't start after deployment
**Causes**:
- YAML syntax error
- Invalid entity reference
- Missing dependency
- Configuration conflict

**Solutions**:
1. Check YAML syntax: `ha core check`
2. Validate entity references
3. Check dependencies
4. Restore from backup
5. Fix configuration issues

#### Automation Not Working After Deployment
**Symptoms**: New automation doesn't work
**Causes**:
- Entity not available
- Configuration error
- Missing dependency
- Automation not enabled

**Solutions**:
1. Check entity availability
2. Verify automation configuration
3. Check dependencies
4. Enable automation
5. Test automation manually

## 🔧 **DEBUGGING TECHNIQUES**

### Log Analysis
```bash
# Check Home Assistant logs
ha core logs

# Check specific integration logs
ha integration logs <integration>

# Check automation logs
ha automation logs <automation_id>

# Check service logs
ha service logs <service>
```

### Entity Debugging
```bash
# Check entity state
ha states get <entity_id>

# Check entity history
ha states history <entity_id>

# Check entity attributes
ha states get <entity_id> --attributes

# Check entity availability
ha states get <entity_id> --availability
```

### Automation Debugging
```bash
# Check automation state
ha automation list

# Check automation configuration
ha automation get <automation_id>

# Test automation manually
ha automation trigger <automation_id>

# Check automation logs
ha automation logs <automation_id>
```

### Service Debugging
```bash
# Check service availability
ha service list

# Check service configuration
ha service get <service>

# Test service manually
ha service call <service> <method> <parameters>

# Check service logs
ha service logs <service>
```

## 📊 **MONITORING AND ALERTING**

### System Health Checks
```bash
# Check system status
ha core info

# Check disk usage
df -h

# Check memory usage
free -h

# Check CPU usage
top

# Check network connectivity
ping google.com
```

### Automation Monitoring
```bash
# Check automation execution
ha automation list

# Check automation errors
ha automation logs <automation_id> --level error

# Check automation performance
ha automation logs <automation_id> --level info
```

### Entity Monitoring
```bash
# Check entity availability
ha states list --unavailable

# Check entity errors
ha states list --error

# Check entity performance
ha states list --slow
```

## 🚨 **ERROR CODES AND SOLUTIONS**

### Common Error Codes
- **404**: Entity not found
- **500**: Internal server error
- **503**: Service unavailable
- **Timeout**: Request timed out
- **Connection refused**: Can't connect to service

### Error Solutions
1. **404 Entity not found**:
   - Check entity ID spelling
   - Verify entity exists
   - Check entity availability

2. **500 Internal server error**:
   - Check logs for details
   - Restart Home Assistant
   - Check configuration

3. **503 Service unavailable**:
   - Check service status
   - Restart service
   - Check dependencies

4. **Timeout**:
   - Check network connection
   - Increase timeout value
   - Check service performance

5. **Connection refused**:
   - Check service status
   - Check network connectivity
   - Restart service

## 📝 **TROUBLESHOOTING CHECKLIST**

### Before Asking for Help
- [ ] **Checked logs** for error details
- [ ] **Verified entity** availability
- [ ] **Tested automation** manually
- [ ] **Checked configuration** syntax
- [ ] **Restarted** relevant services
- [ ] **Checked network** connectivity
- [ ] **Verified dependencies** are met
- [ ] **Documented** the issue

### Information to Provide
- **Error message**: Exact error text
- **Logs**: Relevant log entries
- **Configuration**: Related config files
- **Steps to reproduce**: How to trigger the issue
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happens
- **System info**: Home Assistant version, OS, etc.

## 🔄 **PREVENTIVE MAINTENANCE**

### Daily Checks
- [ ] **Check logs** for errors
- [ ] **Verify** critical automations
- [ ] **Check** entity availability
- [ ] **Monitor** system performance

### Weekly Checks
- [ ] **Review** automation logs
- [ ] **Check** entity inventory
- [ ] **Verify** backup integrity
- [ ] **Update** documentation

### Monthly Checks
- [ ] **Full system** health check
- [ ] **Review** all automations
- [ ] **Clean up** old logs
- [ ] **Update** dependencies

## 🎯 **BEST PRACTICES**

### Prevention
- **Regular backups** before changes
- **Test changes** in safe environment
- **Monitor system** continuously
- **Document everything** thoroughly
- **Use safe deployment** methods

### Response
- **Act quickly** on critical issues
- **Document** all troubleshooting steps
- **Learn** from each issue
- **Improve** processes based on issues
- **Share** knowledge with team

---

**Remember**: Troubleshooting is a skill that improves with practice. Document every issue and solution to build a knowledge base for future reference.
