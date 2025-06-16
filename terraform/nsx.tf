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
    host_switch_id = vsphere_distributed_virtual_switch.vds01.id

    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay_tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan_tz.path
    }

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
  server                 = "10.0.2.2"
  create_service_account = true
  set_as_oidc_provider   = true
  credential {
    username_password_login {
      username   = var.vcenter_username
      password   = var.vcenter_password
      thumbprint = "DB:1E:C0:F7:AD:02:37:92:D8:13:89:1A:C9:12:02:5B:36:79:A8:20:B1:C2:2B:D1:6B:0F:9D:B4:F2:4E:58:C8"
    }
  }
  origin_type = "vCenter"
}

resource "nsxt_policy_host_transport_node_collection" "amd-vmcl02" {
  display_name                = "amd-vmcl02"
  compute_collection_id = "${nsxt_compute_manager.Homelab.id}:${vsphere_compute_cluster.cl02.id}"
  transport_node_profile_path = nsxt_policy_host_transport_node_profile.tnp1.path
  tag {
    scope = "color"
    tag   = "red"
  }
}

resource "nsxt_edge_cluster" "edge_cluster" {
  description  = "Terraform provisioned Edge Cluster"
  display_name = "amd-nxec01"
  member {
    display_name      = "amd-nxen02"
    transport_node_id = "0e83629a-6eb8-4c68-a5df-c5735e63e700"
  }
  member {
    display_name      = "amd-nxen01"
    transport_node_id = "c6f715b0-a2c0-421c-bf93-65774b3102f4"
  }
}

data "nsxt_policy_edge_cluster" "edge_cluster" {
  display_name = "amd-nxec01"
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
  depends_on = [nsxt_edge_cluster.edge_cluster]
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
  edge_cluster_path         = data.nsxt_policy_edge_cluster.edge_cluster.path
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
