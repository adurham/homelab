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

resource "nsxt_policy_host_transport_node_profile" "tnp1" {
  display_name = "tnp.1"

  standard_host_switch {
    ip_assignment {
      assigned_by_dhcp = true
    }
    host_switch_type = "VDS"
    host_switch_id   = vsphere_distributed_virtual_switch.vds01.id
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.esx_host_switch_profile.path
    ]
    is_migrate_pnics = false
    uplink {
      vds_uplink_name = "Uplink 1"
      uplink_name     = "Uplink-1"
    }
    uplink {
      vds_uplink_name = "Uplink 2"
      uplink_name     = "Uplink-2"
    }
  }
}

resource "nsxt_compute_manager" "Homelab" {
  description  = "Compute Manager"
  display_name = "Homelab"
  # tag {
  #   scope = "scope1"
  #   tag   = "tag1"
  # }
  server                 = "10.0.2.2"
  create_service_account = true
  set_as_oidc_provider   = true
  credential {
    username_password_login {
      username   = var.vcenter_username
      password   = var.vcenter_password
      thumbprint = "07:31:4C:28:D0:10:56:7B:6A:2C:C8:72:C9:0F:32:4D:BD:96:FF:32:DC:77:63:83:0D:E9:EC:26:68:2C:6D:A4"
    }
  }
  origin_type = "vCenter"
}

resource "nsxt_policy_host_transport_node_collection" "amd-vmcl01" {
  display_name                = "amd-vmcl01"
  compute_collection_id       = "${nsxt_compute_manager.Homelab.id}:${vsphere_compute_cluster.cl01.id}"
  transport_node_profile_path = nsxt_policy_host_transport_node_profile.tnp1.path
  tag {
    scope = "color"
    tag   = "red"
  }
}

resource "nsxt_policy_host_transport_node_collection" "amd-vmcl02" {
  display_name                = "amd-vmcl02"
  compute_collection_id       = "${nsxt_compute_manager.Homelab.id}:${vsphere_compute_cluster.cl02.id}"
  transport_node_profile_path = nsxt_policy_host_transport_node_profile.tnp1.path
  tag {
    scope = "color"
    tag   = "red"
  }
}

resource "nsxt_transport_node" "edge_node1" {
  display_name = "amd-nxed02-01"
  description  = "Terraform-deployed edge node"
  standard_host_switch {
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.edge_host_switch_profile.realized_id
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
      transport_zone = nsxt_policy_transport_zone.overlay_tz.realized_id
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.realized_id
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
        storage_id = "datastore-14"
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
      nsxt_policy_uplink_host_switch_profile.edge_host_switch_profile.realized_id
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
      transport_zone = nsxt_policy_transport_zone.overlay_tz.realized_id
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.realized_id
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
        storage_id = "datastore-14"
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

resource "nsxt_policy_tier0_gateway" "tier0_gw" {
  description              = "Tier-0 provisioned by Terraform"
  display_name             = "tier0_gw"
  failover_mode            = "NON_PREEMPTIVE"
  default_rule_logging     = false
  enable_firewall          = true
  ha_mode                  = "ACTIVE_STANDBY"
  internal_transit_subnets = ["169.254.0.0/24"]
  transit_subnets          = ["100.64.0.0/16"]
  bgp_config {
    local_as_num    = "65001"
    multipath_relax = true
  }
  edge_cluster_path = data.nsxt_policy_edge_cluster.edge_cluster.path
}

resource "nsxt_policy_vlan_segment" "edge_uplink" {
  display_name        = "Edge_Uplink"
  description         = "Terraform provisioned VLAN Segment"
  transport_zone_path = nsxt_policy_transport_zone.vlan_tz.path
  vlan_ids            = ["9"]
}

resource "nsxt_policy_tier0_gateway_interface" "if1" {
  display_name = "tier0_gw_uplink01"
  description  = "connection for tier0_gw"
  type         = "EXTERNAL"
  //TO-DO Need to BETTER dynamically assign this
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/${nsxt_edge_cluster.edge_cluster.id}/edge-nodes/${nsxt_edge_cluster.edge_cluster.member[1].member_index}"
  gateway_path   = nsxt_policy_tier0_gateway.tier0_gw.path
  //TO-DO Need to dynamically assign this
  segment_path = nsxt_policy_vlan_segment.edge_uplink.path
  subnets      = ["10.0.3.130/26"]
  mtu          = 2100
}

resource "nsxt_policy_tier0_gateway_interface" "if2" {
  display_name = "tier0_gw_uplink02"
  description  = "connection for tier0_gw"
  type         = "EXTERNAL"
  //TO-DO Need to BETTER dynamically assign this
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/${nsxt_edge_cluster.edge_cluster.id}/edge-nodes/${nsxt_edge_cluster.edge_cluster.member[0].member_index}"
  gateway_path   = nsxt_policy_tier0_gateway.tier0_gw.path
  //TO-DO Need to dynamically assign this
  segment_path = nsxt_policy_vlan_segment.edge_uplink.path
  subnets      = ["10.0.3.131/26"]
  mtu          = 2100
}

resource "nsxt_policy_bgp_neighbor" "tier0_gw_bgp" {
  display_name          = "tier0_gw_bgp"
  description           = "Terraform provisioned BgpNeighborConfig"
  bgp_path              = nsxt_policy_tier0_gateway.tier0_gw.bgp_config.0.path
  allow_as_in           = true
  graceful_restart_mode = "HELPER_ONLY"
  hold_down_time        = 300
  keep_alive_time       = 100
  neighbor_address      = "10.0.3.129"
  remote_as_num         = "65000"
  source_addresses = [
    nsxt_policy_tier0_gateway_interface.if1.ip_addresses[0],
    nsxt_policy_tier0_gateway_interface.if2.ip_addresses[0]
  ]
  bfd_config {
    enabled  = true
    interval = 1000
    multiple = 4
  }
}

resource "nsxt_policy_gateway_redistribution_config" "tier0_gw" {
  gateway_path = nsxt_policy_tier0_gateway.tier0_gw.path
  bgp_enabled  = true
  rule {
    name = "rule-1"
    types = [
      "TIER1_NAT",
      "TIER1_STATIC",
      "TIER1_LB_VIP",
      "TIER1_LB_SNAT",
      "TIER1_DNS_FORWARDER_IP",
      "TIER1_CONNECTED",
      "TIER1_SERVICE_INTERFACE",
      "TIER1_SEGMENT",
      "TIER1_IPSEC_LOCAL_ENDPOINT"
    ]
  }
}

resource "nsxt_policy_tier1_gateway" "tier1_gw" {
  description  = "Tier-1 provisioned by Terraform"
  display_name = "tier1-gw1"
  depends_on = [
    nsxt_edge_cluster.edge_cluster
  ]
  # edge_cluster_path         = data.nsxt_policy_edge_cluster.edge_cluster.path
  ha_mode                   = "ACTIVE_STANDBY"
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
