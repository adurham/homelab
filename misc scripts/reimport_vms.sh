#!/bin/bash

# Helper function to generate abbreviated OS prefix for VM names
abbreviate_os() {
  case "$1" in
    "Ubuntu") echo "ubnt" ;;
    "RHEL") echo "rhel" ;;
    "Oracle") echo "oel" ;;
    "Windows") echo "wn" ;;
    "Debian") echo "db" ;;
    *) echo "unknown" ;;
  esac
}

# Function to perform terraform import with correct naming conventions
perform_import() {
  local os_name=$1
  local version=$2
  local os_prefix=$(abbreviate_os "$os_name") # For VM hostname abbreviation
  local version_suffix="${version// /}" # Remove spaces for Windows versions
  local module_name_suffix="$version_suffix" # Default module name suffix

  if [[ "$os_name" == "Windows" ]]; then
    version_suffix=$(echo "$version_suffix" | tr '[:upper:]' '[:lower:]') # Convert to lowercase
    version_suffix=$(echo "$version_suffix" | tr 'R' 'r') # Convert R2 -> r2
    if [[ "$version" == "2012 R2" ]]; then
      module_name_suffix="server_2012r2" # Correct suffix for module name
      # For Windows Server 2012, specifically omit 'r2' in VM hostname
      version_suffix="2012"
    else
      module_name_suffix="server_$version_suffix" # Full "server_YEAR" format for module name
    fi
  fi

  # Use tr to convert OS name to lowercase for the module name
  local os_name_lower=$(echo "$os_name" | tr '[:upper:]' '[:lower:]')
  local module_name="module.homelab-tanium_clients_76-${os_name_lower}_${module_name_suffix}"

  # Generate VM hostname using the abbreviated OS prefix and version
  local hostname="/Homelab/vm/Tanium/Clients/tn76-${os_prefix}${version_suffix}"

  # Execute terraform import commands for both VMs [0] and [1]
  echo "Importing ${module_name}.vsphere_virtual_machine.vm[0] with ${hostname}-01"
  terraform import "${module_name}.vsphere_virtual_machine.vm[0]" "${hostname}-01"
  echo "Importing ${module_name}.vsphere_virtual_machine.vm[1] with ${hostname}-02"
  terraform import "${module_name}.vsphere_virtual_machine.vm[1]" "${hostname}-02"
}

# Ubuntu versions
for version in 18 20 22; do
  perform_import "Ubuntu" "$version"
done

# RHEL versions
for version in 6 7 8 9; do
  perform_import "RHEL" "$version"
done

# OEL versions
for version in 6 7 8 9; do
  perform_import "Oracle" "$version"
done

# Win versions
windows_versions=("2012 R2" "2016" "2019" "2022")
for version in "${windows_versions[@]}"; do
    perform_import "Windows" "$version"
done