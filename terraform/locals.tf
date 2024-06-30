locals {
  # Common Settings
  dns_servers = ["10.0.3.129"]
  lease_time  = 86400

  # Datastores
  datastore_flash = "vSphere Flash"
  datastore_rust  = "vSphere Rust"
  datastore_vsan  = "vsanDatastore"

  # Clusters
  cl01_resource_pool = "${vsphere_compute_cluster.cl01.name}/Resources"
  cl02_resource_pool = "${vsphere_compute_cluster.cl02.name}/Resources"

  # Low Resource VM Specs
  low_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "low"
    io_share_level  = ["low"]
  }

  # Network Configurations
  tanium_clients_74_network = nsxt_policy_fixed_segment.tanium_clients_74.display_name
  tanium_clients_74_gateway = "172.16.4.1"
  peering_test_gateway      = "172.16.7.1"
  keycloak_gateway          = "172.16.0.161"

  # Active Directory Settings
  active_directory_cidr     = "172.16.0.1/25"
  active_directory_vmgw     = "172.16.0.1"
  active_directory_ips      = ["172.16.0.3", "172.16.0.4", "172.16.0.5"]
  federation_services_ips   = ["172.16.0.6", "172.16.0.7", "172.16.0.8"]
  certificate_authority_ips = ["172.16.0.9", "172.16.0.10", "172.16.0.11"]
  active_directory_resource_vm_specs = {
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
