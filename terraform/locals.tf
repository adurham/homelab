locals {
  # Common Settings
  dns_servers = ["10.0.3.129"]
  lease_time  = 86400

  # Datastores
  datastore_flash       = "vSphere Flash"
  datastore_rust        = "vSphere Rust"
  datastore_vsandatastore = "vsanDatastore"

  # Clusters
  cl01_resource_pool   = "${vsphere_compute_cluster.cl01.name}/Resources"
  cl02_resource_pool   = "${vsphere_compute_cluster.cl02.name}/Resources"

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
}
