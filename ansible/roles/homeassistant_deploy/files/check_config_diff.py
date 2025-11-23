#!/usr/bin/env python3
import sys
import yaml
import os

class TaggedValue:
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value
    
    def __eq__(self, other):
        if isinstance(other, TaggedValue):
            return self.tag == other.tag and self.value == other.value
        return False
    
    def __repr__(self):
        return f"{self.tag} {self.value}"

def create_loader(secrets=None):
    class HALoader(yaml.SafeLoader):
        pass

    def secret_constructor(loader, node):
        value = loader.construct_scalar(node)
        if secrets and value in secrets:
            return secrets[value]
        return TaggedValue('!secret', value)

    def generic_constructor(tag):
        def constructor(loader, node):
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
            elif isinstance(node, yaml.SequenceNode):
                value = loader.construct_sequence(node)
            elif isinstance(node, yaml.MappingNode):
                value = loader.construct_mapping(node)
            else:
                value = None
            return TaggedValue(tag, value)
        return constructor

    HALoader.add_constructor('!secret', secret_constructor)
    
    for tag in ['!include', '!env_var', '!include_dir_list', '!include_dir_merge_list', 
                '!include_dir_named', '!include_dir_merge_named', '!input']:
        HALoader.add_constructor(tag, generic_constructor(tag))

    return HALoader

def load_yaml(config_path, secrets=None):
    loader_cls = create_loader(secrets)
    with open(config_path, 'r') as f:
        return yaml.load(f, Loader=loader_cls)

def main():
    if len(sys.argv) != 4:
        print("Usage: check_config_diff.py <local_config> <remote_config> <secrets_file>")
        sys.exit(1)

    local_config_path = sys.argv[1]
    remote_config_path = sys.argv[2]
    secrets_path = sys.argv[3]

    try:
        # Load secrets
        try:
            with open(secrets_path, 'r') as f:
                secrets = yaml.safe_load(f) or {}
        except FileNotFoundError:
            secrets = {}

        # Load local with secret expansion
        local_data = load_yaml(local_config_path, secrets)
        
        # Load remote with secret expansion (secrets are deployed now)
        remote_data = load_yaml(remote_config_path, secrets)

        if local_data == remote_data:
            print("Configuration matches (semantically).")
            sys.exit(0)
        else:
            print("Configuration differs.")
            sys.exit(1)

    except Exception as e:
        print(f"Error comparing configurations: {e}")
        sys.exit(2)

if __name__ == "__main__":
    main()
