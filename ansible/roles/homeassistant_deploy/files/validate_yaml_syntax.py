#!/usr/bin/env python3
"""
Validate YAML syntax for all YAML files in Home Assistant configuration.
This catches syntax errors before deployment.
Handles HA-specific tags like !include, !secret, etc.
"""
import sys
import yaml
import os
from pathlib import Path

class TaggedValue:
    """Placeholder for tagged values - we just need to parse them, not evaluate"""
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value

def create_haloader():
    """Create a YAML loader that handles Home Assistant specific tags."""
    class HALoader(yaml.SafeLoader):
        pass
    
    def generic_constructor(loader, node):
        """Generic constructor for HA tags - just create a placeholder"""
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node)
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node)
        else:
            value = None
        return TaggedValue(node.tag, value)
    
    # Register all common HA tags
    for tag in ['!include', '!secret', '!env_var', '!include_dir_list', 
                '!include_dir_merge_list', '!include_dir_named', 
                '!include_dir_merge_named', '!input']:
        HALoader.add_constructor(tag, generic_constructor)
    
    return HALoader

def validate_yaml_file(file_path):
    """Validate a single YAML file for syntax errors."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Use custom loader that handles HA tags
            yaml.load(content, Loader=create_haloader())
        return None  # No error
    except yaml.YAMLError as e:
        return f"YAML syntax error in {file_path}: {e}"
    except Exception as e:
        return f"Error reading {file_path}: {e}"

def main():
    if len(sys.argv) < 2:
        print("Usage: validate_yaml_syntax.py <directory>")
        sys.exit(1)
    
    base_dir = Path(sys.argv[1]).resolve()
    if not base_dir.exists():
        print(f"Error: Directory {base_dir} does not exist", file=sys.stderr)
        sys.exit(1)
    
    if not base_dir.is_dir():
        print(f"Error: {base_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    
    errors = []
    
    # Find all YAML files in the directory tree
    files_to_check = list(base_dir.rglob('*.yaml')) + list(base_dir.rglob('*.yml'))
    # Exclude venv and other common directories
    files_to_check = [
        f for f in files_to_check 
        if 'venv' not in str(f) and '__pycache__' not in str(f) and '.git' not in str(f)
    ]
    
    for file_path in sorted(files_to_check):
        if file_path.exists() and file_path.is_file():
            error = validate_yaml_file(file_path)
            if error:
                errors.append(error)
                print(error, file=sys.stderr)
    
    if errors:
        print(f"\nFound {len(errors)} YAML syntax error(s)", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"✓ All {len(files_to_check)} YAML file(s) validated successfully")
        sys.exit(0)

if __name__ == "__main__":
    main()

