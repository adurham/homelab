# Home Assistant Entity Inventory

This directory contains tools for managing and auditing Home Assistant entities and automations.

## Files

- `extract_with_config.py` - Extract entities using API token from ha_config.env
- `simple_audit.py` - Audit automations against entity inventory
- `fix_automations.py` - Fix automation issues found in audit

## Usage

1. Ensure `ha_config.env` contains your Home Assistant API token
2. Run `python3 extract_with_config.py` to extract entities
3. Run `python3 simple_audit.py` to audit automations
4. Run `python3 fix_automations.py` to fix issues

## Generated Files

The following files are generated and should not be committed:
- `entity_inventory.json` - Entity inventory data
- `entity_inventory.md` - Human-readable entity documentation
- `automation_audit_*` - Audit reports and results
- `clean_automations.json` - Clean automation list

These files are automatically ignored by git.
