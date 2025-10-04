# Home Assistant Deployment Rules

## 🚨 **CRITICAL DEPLOYMENT RULES**

### Pre-Deployment Checklist
- [ ] **Backup created** - Always create backup before deployment
- [ ] **Code reviewed** - All changes reviewed and tested
- [ ] **Entity validated** - All entity references verified
- [ ] **Dependencies checked** - All required entities exist
- [ ] **Logging added** - Comprehensive logging included
- [ ] **Error handling** - Proper error handling implemented
- [ ] **Documentation updated** - All changes documented

### Deployment Safety Rules
- **NEVER** deploy during active use without warning
- **ALWAYS** use safe deployment scripts
- **NEVER** manually edit files on Home Assistant box
- **ALWAYS** test in safe environment first
- **NEVER** deploy untested code
- **ALWAYS** monitor logs during deployment

## 🔧 **DEPLOYMENT METHODS**

### Method 1: Safe Deployment (Recommended)
```bash
# Use the safe deployment script
./deployment/safe_deploy.py --backup --validate --test
```

### Method 2: Minimal Deployment
```bash
# Use minimal deployment for quick changes
./deployment/minimal_deploy.sh --files-only
```

### Method 3: Ansible Deployment
```bash
# Use Ansible for complex deployments
ansible-playbook -i deployment/inventory.yml deployment/deploy_homeassistant.yml
```

## 📋 **DEPLOYMENT WORKFLOW**

### Step 1: Pre-Deployment
1. **Create backup** of current configuration
2. **Validate** all entity references
3. **Test** changes in safe environment
4. **Review** all modified files
5. **Check** for sensitive data

### Step 2: Deployment
1. **Stop** any running automations (if necessary)
2. **Deploy** using safe deployment script
3. **Monitor** logs during deployment
4. **Verify** all files deployed correctly
5. **Restart** Home Assistant if needed

### Step 3: Post-Deployment
1. **Test** all critical functions
2. **Check** logs for errors
3. **Verify** automations are working
4. **Monitor** system for 24 hours
5. **Document** any issues found

## 🚫 **FORBIDDEN DEPLOYMENT PRACTICES**

### Never Do These
- ❌ **Deploy without backup**
- ❌ **Deploy untested code**
- ❌ **Deploy during active use**
- ❌ **Manual file editing on HA box**
- ❌ **Deploy sensitive data**
- ❌ **Skip validation steps**
- ❌ **Deploy without monitoring**

### Anti-Patterns
- ❌ **Deploying everything at once**
- ❌ **No rollback plan**
- ❌ **Silent deployments**
- ❌ **No testing**
- ❌ **No documentation**

## 🔄 **ROLLBACK PROCEDURES**

### Emergency Rollback
1. **Stop** all automations
2. **Restore** from latest backup
3. **Restart** Home Assistant
4. **Verify** system is working
5. **Investigate** what went wrong

### Planned Rollback
1. **Identify** problematic changes
2. **Create** rollback plan
3. **Test** rollback procedure
4. **Execute** rollback
5. **Verify** system stability

## 📊 **DEPLOYMENT MONITORING**

### During Deployment
- **Monitor logs** for errors
- **Check file transfers** completed
- **Verify permissions** set correctly
- **Test critical functions** immediately
- **Watch for warnings** in logs

### Post-Deployment
- **Monitor system** for 24 hours
- **Check automation** execution
- **Verify entity** availability
- **Test edge cases** and failures
- **Document** any issues

## 🚨 **DEPLOYMENT ERROR HANDLING**

### Common Deployment Errors
- **File transfer failed**: Check SSH connection
- **Permission denied**: Check file permissions
- **Entity not found**: Validate entity references
- **Configuration error**: Check YAML syntax
- **Service unavailable**: Check Home Assistant status

### Error Recovery
```bash
# Check deployment status
./deployment/test_deployment.py

# Verify file integrity
ssh root@192.168.86.2 "ls -la /config/automations/"

# Check Home Assistant logs
ssh root@192.168.86.2 "ha core logs"
```

## 📝 **DEPLOYMENT DOCUMENTATION**

### Required Documentation
- **Deployment log**: What was deployed when
- **Change log**: What changed in each deployment
- **Rollback procedures**: How to rollback if needed
- **Dependencies**: What each deployment requires
- **Testing procedures**: How to test after deployment

### Deployment Log Template
```markdown
## Deployment Log - 2024-01-15

**Deployed by**: [Name]
**Deployment method**: Safe deployment script
**Files changed**: 
  - automations/garage_lights_enhanced.yaml
  - python_scripts/pause_all_timers_script.py
**Backup created**: backup/20240115_143022
**Testing performed**: 
  - Garage lights automation tested
  - Timer pause/resume tested
**Issues found**: None
**Rollback plan**: Restore from backup/20240115_143022
```

## 🔧 **DEPLOYMENT TOOLS**

### Safe Deployment Script
```bash
# Full safe deployment
./deployment/safe_deploy.py --backup --validate --test --deploy

# Quick deployment (files only)
./deployment/minimal_deploy.sh --files-only

# Test deployment (no changes)
./deployment/safe_deploy.py --validate --test
```

### Deployment Validation
```bash
# Validate configuration
./deployment/test_deployment.py

# Check entity references
./entity_inventory/simple_audit.py

# Verify file integrity
./deployment/deploy_to_ha.py --validate
```

## 🎯 **DEPLOYMENT BEST PRACTICES**

### Planning
- **Plan deployments** during low-usage periods
- **Test thoroughly** before deployment
- **Have rollback plan** ready
- **Notify users** of planned changes
- **Document everything**

### Execution
- **Use safe deployment** scripts
- **Monitor closely** during deployment
- **Test immediately** after deployment
- **Document results** and issues
- **Clean up** temporary files

### Post-Deployment
- **Monitor system** for 24 hours
- **Test all functions** thoroughly
- **Update documentation** if needed
- **Plan next deployment** based on results
- **Learn from issues** encountered

## 🚨 **EMERGENCY PROCEDURES**

### If Deployment Fails
1. **Stop deployment** immediately
2. **Check logs** for error details
3. **Restore from backup** if necessary
4. **Investigate** root cause
5. **Fix issue** before retrying
6. **Document** failure and solution

### If System Breaks After Deployment
1. **Stop all automations** immediately
2. **Restore from backup** if necessary
3. **Restart Home Assistant**
4. **Verify system** is working
5. **Investigate** what went wrong
6. **Fix and test** before redeploying

## 📊 **DEPLOYMENT METRICS**

### Success Metrics
- **Zero** deployment failures
- **100%** backup success rate
- **Fast** deployment times (< 5 minutes)
- **Zero** post-deployment issues
- **Complete** documentation

### Quality Metrics
- **All tests** pass before deployment
- **All validations** pass
- **All documentation** updated
- **All backups** created
- **All monitoring** in place

---

**Remember**: Deployment is the most critical phase of development. Follow these rules religiously to maintain system stability and reliability.
