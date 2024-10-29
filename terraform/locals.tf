locals {
  # Common Settings
  dns_servers = ["10.0.3.129"]
  lease_time  = 86400

  # Datastores
  datastore_flash = "vSphere Flash"
  datastore_rust  = "vSphere Rust"
  datastore_vsan  = "vsanDatastore"

  # Clusters
  # cl01_resource_pool = "${vsphere_compute_cluster.cl01.name}/Resources"
  cl02_resource_pool = "${vsphere_compute_cluster.cl02.name}/Resources"

  # Low Resource VM Specs
  low_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "low"
    io_share_level  = ["low"]
  }

  # Network Configurations
  # tanium_clients_74_network = nsxt_policy_fixed_segment.tanium_clients_74.display_name
  # tanium_clients_74_gateway = "172.16.4.1"
  # peering_test_gateway      = "172.16.7.1"

  # Active Directory Settings
  active_directory_cidr         = "172.16.0.1/25"
  active_directory_gateway      = cidrhost(local.active_directory_cidr, 1)
  active_directory_netmask      = [cidrnetmask(local.active_directory_cidr)]
  active_directory_netmask_cidr = [tonumber(regex("^[0-9\\.]+/(\\d+)$", local.active_directory_cidr)[0])]
  active_directory_ips          = ["172.16.0.3", "172.16.0.4", "172.16.0.5"]
  federation_services_ips       = ["172.16.0.6", "172.16.0.7", "172.16.0.8"]
  certificate_authority_ips     = ["172.16.0.9", "172.16.0.10", "172.16.0.11"]
  active_directory_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "normal"
    io_share_level  = ["normal"]
  }

  # Consul settings
  consul_cidr         = "172.16.0.129/28"
  consul_gateway      = cidrhost(local.consul_cidr, 1)
  consul_netmask      = [cidrnetmask(local.consul_cidr)]
  consul_netmask_cidr = [tonumber(regex("^[0-9\\.]+/(\\d+)$", local.consul_cidr)[0])]
  consul_ips          = ["172.16.0.131", "172.16.0.132", "172.16.0.133"]
  consul_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "normal"
    io_share_level  = ["normal"]
  }

  # Vault settings
  vault_cidr         = "172.16.0.145/28"
  vault_gateway      = cidrhost(local.vault_cidr, 1)
  vault_netmask      = [cidrnetmask(local.vault_cidr)]
  vault_netmask_cidr = [tonumber(regex("^[0-9\\.]+/(\\d+)$", local.vault_cidr)[0])]
  vault_ips          = ["172.16.0.146", "172.16.0.147", "172.16.0.148"]
  vault_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "normal"
    io_share_level  = ["normal"]
  }

  # Keycloak settings
  keycloak_cidr         = "172.16.0.161/28"
  keycloak_gateway      = cidrhost(local.keycloak_cidr, 1)
  keycloak_netmask      = [cidrnetmask(local.keycloak_cidr)]
  keycloak_netmask_cidr = [tonumber(regex("^[0-9\\.]+/(\\d+)$", local.keycloak_cidr)[0])]
  keycloak_ips          = ["172.16.0.162"]
  keycloak_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "normal"
    io_share_level  = ["normal"]
  }

  # Edge Node Paths
  edge_node_path_1 = format(
    "/infra/sites/default/enforcement-points/default/edge-clusters/%s/edge-nodes/%s",
    nsxt_edge_cluster.edge_cluster.id,
    nsxt_edge_cluster.edge_cluster.member[1].member_index
  )
  edge_node_path_0 = format(
    "/infra/sites/default/enforcement-points/default/edge-clusters/%s/edge-nodes/%s",
    nsxt_edge_cluster.edge_cluster.id,
    nsxt_edge_cluster.edge_cluster.member[0].member_index
  )

  # Common Settings for VMs
  ws22dc_template    = "Windows Server 2022 Datacenter"
  vsphere_datacenter = "Homelab"
}
