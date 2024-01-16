resource "nsxt_policy_transport_zone" "overlay_tz" {
  display_name   = "nsx.overlay_tz.1GbE0"
  description    = "Terraform-deployed Overlay transport zone"
  transport_type = "OVERLAY_BACKED"
}

resource "nsxt_policy_transport_zone" "vlan_tz" {
  display_name   = "nsx.vlan_tz.networking.1GbE0"
  description    = "Terraform-deployed VLAN transport zone"
  transport_type = "VLAN_BACKED"
}

resource "nsxt_policy_uplink_host_switch_profile" "esx_host_switch_profile" {
  description    = "ESX host switch profile provisioned by Terraform"
  display_name   = "esx_host_switch_profile"
  transport_vlan = 7
  overlay_encap  = "GENEVE"
  teaming {
    active {
      uplink_name = "Uplink-1"
      uplink_type = "PNIC"
    }
    active {
      uplink_name = "Uplink-2"
      uplink_type = "PNIC"
    }
    policy = "FAILOVER_ORDER"
  }
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_uplink_host_switch_profile" "edge_host_switch_profile" {
  description    = "Edge host switch profile provisioned by Terraform"
  display_name   = "edge_host_switch_profile"
  mtu            = 2100
  transport_vlan = 8
  overlay_encap  = "GENEVE"
  named_teaming {
    active {
      uplink_name = "Uplink-1"
      uplink_type = "PNIC"
    }
    policy = "FAILOVER_ORDER"
    name   = "Uplink-1"
  }
  named_teaming {
    active {
      uplink_name = "Uplink-2"
      uplink_type = "PNIC"
    }
    policy = "FAILOVER_ORDER"
    name   = "Uplink-2"
  }
  teaming {
    active {
      uplink_name = "Uplink-1"
      uplink_type = "PNIC"
    }
    active {
      uplink_name = "Uplink-2"
      uplink_type = "PNIC"
    }
    policy = "LOADBALANCE_SRCID"
  }
  tag {
    scope = "color"
    tag   = "blue"
  }
}

// Need to figure out if I NEED an Edge IP pool, or if I can just use DHCP
resource "nsxt_policy_ip_pool" "edge_host_transport_node_ip_pool" {
  description  = "ip_pool provisioned by Terraform"
  display_name = "Edge-TEP-IP-Pool"
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_ip_pool_static_subnet" "edge_host_transport_node_static_pool" {
  display_name = "Edge-TEP-IP-Pool"
  pool_path    = nsxt_policy_ip_pool.edge_host_transport_node_ip_pool.path
  cidr         = "10.0.3.64/26"
  gateway      = "10.0.3.65"
  dns_suffix   = var.domain
  dns_nameservers = [
    "10.0.3.65"
  ]
  allocation_range {
    start = "10.0.3.66"
    end   = "10.0.3.126"
  }
}

resource "nsxt_compute_manager" "Homelab" {
  description  = "Compute Manager"
  display_name = "Homelab"
  # tag {
  #   scope = "scope1"
  #   tag   = "tag1"
  # }
  server                 = "amd-vmvc01.lab.amd-e.com"
  create_service_account = true
  set_as_oidc_provider   = true
  credential {
    username_password_login {
      username   = var.vcenter_username
      password   = var.vcenter_password
      thumbprint = "17:19:5A:E8:6E:DB:12:36:93:4E:63:1B:65:DD:A2:67:2A:AC:39:63:FC:9C:0C:FD:FB:BF:BB:C4:62:D6:E2:6B"
    }
  }
  origin_type = "vCenter"
}

resource "nsxt_policy_host_transport_node" "amd-hwvm01" {
  display_name      = "amd-hwvm01.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm01_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "7.0.3"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm02" {
  display_name      = "amd-hwvm02.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm02_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "7.0.3"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm03" {
  display_name      = "amd-hwvm03.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm03_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "7.0.3"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm04" {
  display_name      = "amd-hwvm04.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm04_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "7.0.3"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm05" {
  display_name      = "amd-hwvm05.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm05_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "8.0.2"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm06" {
  display_name      = "amd-hwvm06.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm06_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "8.0.2"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm07" {
  display_name      = "amd-hwvm07.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm07_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "8.0.2"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm08" {
  display_name      = "amd-hwvm08.${var.domain}"
  description       = "Terraform-deployed host transport node"
  site_path         = "/infra/sites/default"
  enforcement_point = "default"
  node_deployment_info {
    ip_addresses = [
      data.vsphere_host_thumbprint.amd-hwvm08_thumbprint.address
    ]
    os_type    = "ESXI"
    os_version = "8.0.2"
  }
  standard_host_switch {
    host_switch_mode = "STANDARD"
    host_switch_type = "VDS"
    host_switch_id   = "50 29 06 ed 9c 31 f7 32-7d 11 11 19 4b 35 93 ce"
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = true
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    uplink {
      uplink_name     = "Uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "Uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_transport_node" "edge_node1" {
  display_name = "amd-nxed02-01"
  description  = "Terraform-deployed edge node"
  standard_host_switch {
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.edge_host_switch_profile.id
    ]
    // TO-DO Need to dynamically assign this
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = "fd15df55-2b2a-4709-9d4e-2e06bfcc65b2"
    }
    pnic {
      device_name = "fp-eth0"
      uplink_name = "Uplink-1"
    }
    pnic {
      device_name = "fp-eth1"
      uplink_name = "Uplink-2"
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.id
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.id
    }
  }
  edge_node {
    deployment_config {
      form_factor = "MEDIUM"
      node_user_settings {
        cli_username  = var.nsx_transport_node_cli_username
        cli_password  = var.nsx_transport_node_cli_password
        root_password = var.nsx_transport_node_root_password
      }
      vm_deployment_config {
        compute_id = vsphere_compute_cluster.cl02.resource_pool_id
        data_network_ids = [
          vsphere_distributed_port_group.vds01_vdpg01.id,
          vsphere_distributed_port_group.vds01_vdpg01.id
        ]
        default_gateway_address = []
        ipv4_assignment_enabled = true
        management_network_id   = vsphere_distributed_port_group.vds02_vdpg04.id
        // TO-DO Need to dynamically assign this
        storage_id = "datastore-25"
        vc_id      = nsxt_compute_manager.Homelab.id
        reservation_info {
          cpu_reservation_in_mhz        = 0
          cpu_reservation_in_shares     = "HIGH_PRIORITY"
          memory_reservation_percentage = 100
        }
      }
    }
    node_settings {
      hostname = "amd-nxed02-01.${var.domain}"
      dns_servers = [
        "10.0.2.1"
      ]
      enable_ssh      = false
      enable_upt_mode = true
      ntp_servers = [
        "10.0.2.1"
      ]
      search_domains = [
        var.domain
      ]
    }
  }
}

resource "nsxt_transport_node" "edge_node2" {
  display_name = "amd-nxed02-02"
  description  = "Terraform-deployed edge node"
  standard_host_switch {
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.edge_host_switch_profile.id
    ]
    // TO-DO Need to dynamically assign this
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = "fd15df55-2b2a-4709-9d4e-2e06bfcc65b2"
    }
    pnic {
      device_name = "fp-eth0"
      uplink_name = "Uplink-1"
    }
    pnic {
      device_name = "fp-eth1"
      uplink_name = "Uplink-2"
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.id
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.id
    }
  }
  edge_node {
    deployment_config {
      form_factor = "MEDIUM"
      node_user_settings {
        cli_username  = var.nsx_transport_node_cli_username
        cli_password  = var.nsx_transport_node_cli_password
        root_password = var.nsx_transport_node_root_password
      }
      vm_deployment_config {
        compute_id = vsphere_compute_cluster.cl02.resource_pool_id
        data_network_ids = [
          vsphere_distributed_port_group.vds01_vdpg01.id,
          vsphere_distributed_port_group.vds01_vdpg01.id
        ]
        default_gateway_address = []
        ipv4_assignment_enabled = true
        management_network_id   = vsphere_distributed_port_group.vds02_vdpg04.id
        // TO-DO Need to dynamically assign this
        storage_id = "datastore-25"
        vc_id      = nsxt_compute_manager.Homelab.id
        reservation_info {
          cpu_reservation_in_mhz        = 0
          cpu_reservation_in_shares     = "HIGH_PRIORITY"
          memory_reservation_percentage = 100
        }
      }
    }
    node_settings {
      hostname = "amd-nxed02-02.${var.domain}"
      dns_servers = [
        "10.0.2.1"
      ]
      enable_ssh      = false
      enable_upt_mode = true
      ntp_servers = [
        "10.0.2.1"
      ]
      search_domains = [
        var.domain
      ]
    }
  }
}

resource "nsxt_edge_cluster" "edge_cluster" {
  description  = "Terraform provisioned Edge Cluster"
  display_name = "amd-nxedcl01"
  depends_on = [
    nsxt_transport_node.edge_node1,
    nsxt_transport_node.edge_node2
  ]
  member {
    display_name      = nsxt_transport_node.edge_node2.display_name
    transport_node_id = nsxt_transport_node.edge_node2.id
  }
  member {
    display_name      = nsxt_transport_node.edge_node1.display_name
    transport_node_id = nsxt_transport_node.edge_node1.id
  }
}

data "nsxt_policy_edge_cluster" "edge_cluster" {
  display_name = "amd-nxedcl01"
}

//TO-DO no way to set stateful mode here?
resource "nsxt_policy_tier0_gateway" "tier0_gw" {
  description              = "Tier-0 provisioned by Terraform"
  display_name             = "tier0_gw"
  failover_mode            = "NON_PREEMPTIVE"
  default_rule_logging     = false
  enable_firewall          = true
  ha_mode                  = "ACTIVE_ACTIVE"
  internal_transit_subnets = ["169.254.0.0/24"]
  transit_subnets          = ["100.64.0.0/16"]
  bgp_config {
    local_as_num    = "65001"
    multipath_relax = true
  }
  edge_cluster_path = data.nsxt_policy_edge_cluster.edge_cluster.path
}

resource "nsxt_policy_tier0_gateway_interface" "if1" {
  display_name = "tier0_gw_uplink01"
  description  = "connection for tier0_gw"
  type         = "EXTERNAL"
  //TO-DO Need to BETTER dynamically assign this
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/${nsxt_edge_cluster.edge_cluster.id}/edge-nodes/${nsxt_edge_cluster.edge_cluster.member[1].member_index}"
  gateway_path = nsxt_policy_tier0_gateway.tier0_gw.path
  //TO-DO Need to dynamically assign this
  segment_path = "/infra/segments/Edge_Uplink"
  subnets      = ["10.0.3.130/26"]
  mtu          = 2100
}

resource "nsxt_policy_tier0_gateway_interface" "if2" {
  display_name = "tier0_gw_uplink02"
  description  = "connection for tier0_gw"
  type         = "EXTERNAL"
  //TO-DO Need to BETTER dynamically assign this
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/${nsxt_edge_cluster.edge_cluster.id}/edge-nodes/${nsxt_edge_cluster.edge_cluster.member[0].member_index}"
  gateway_path = nsxt_policy_tier0_gateway.tier0_gw.path
  //TO-DO Need to dynamically assign this
  segment_path = "/infra/segments/Edge_Uplink"
  subnets      = ["10.0.3.131/26"]
  mtu          = 2100
}

resource "nsxt_policy_tier1_gateway" "tier1_gw" {
  description  = "Tier-1 provisioned by Terraform"
  display_name = "tier1-gw1"
  depends_on = [
    nsxt_edge_cluster.edge_cluster
  ]
  edge_cluster_path         = data.nsxt_policy_edge_cluster.edge_cluster.path
  ha_mode                   = "ACTIVE_ACTIVE"
  failover_mode             = "NON_PREEMPTIVE"
  default_rule_logging      = "false"
  enable_firewall           = "true"
  enable_standby_relocation = "false"
  tier0_path                = nsxt_policy_tier0_gateway.tier0_gw.path
  //TO-DO Need to dynamically assign this
  dhcp_config_path = "/infra/dhcp-server-configs/Homelab"
  route_advertisement_types = [
    "TIER1_IPSEC_LOCAL_ENDPOINT",
    "TIER1_CONNECTED"
  ]
  pool_allocation = "LB_MEDIUM"
  tag {
    scope = "color"
    tag   = "blue"
  }
}
