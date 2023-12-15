resource "nsxt_policy_transport_zone" "overlay-tz" {
  display_name   = "nsx.overlay-tz.1GbE0"
  description    = "Terraform-deployed Overlay transport zone"
  transport_type = "OVERLAY_BACKED"
}

resource "nsxt_policy_transport_zone" "vlan-tz" {
  display_name   = "nsx.vlan-tz.networking.1GbE0"
  description    = "Terraform-deployed VLAN transport zone"
  transport_type = "VLAN_BACKED"
}

resource "nsxt_policy_uplink_host_switch_profile" "uplink_host_switch_profile" {
  description    = "Uplink host switch profile provisioned by Terraform"
  display_name   = "uplink_host_switch_profile"
  mtu            = 2100
  transport_vlan = 8
  overlay_encap  = "GENEVE"
  named_teaming {
    active {
      uplink_name = "uplink-1"
      uplink_type = "PNIC"
    }
    policy = "FAILOVER_ORDER"
    name   = "teaming-1"
  }
  named_teaming {
    active {
      uplink_name = "uplink-2"
      uplink_type = "PNIC"
    }
    policy = "FAILOVER_ORDER"
    name   = "teaming-2"
  }
  teaming {
    active {
      uplink_name = "uplink-1"
      uplink_type = "PNIC"
    }
    active {
      uplink_name = "uplink-2"
      uplink_type = "PNIC"
    }
    policy = "LOADBALANCE_SRCID"
  }
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_ip_pool" "host_transport_node_ip_pool" {
  description  = "ip_pool provisioned by Terraform"
  display_name = "NSX-ESX-TEP-IP-Pool"
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_ip_pool_static_subnet" "host_transport_node_static_pool" {
  display_name = "NSX-ESX-TEP-IP-Pool"
  pool_path    = nsxt_policy_ip_pool.host_transport_node_ip_pool.path
  cidr         = "10.0.3.0/26"
  gateway      = "10.0.3.1"
  dns_nameservers = [
    "10.0.3.1"
  ]
  allocation_range {
    start = "10.0.3.2"
    end   = "10.0.3.62"
  }
}

resource "nsxt_policy_uplink_host_switch_profile" "host_transport_node_switch_profile" {
  description    = "Uplink host switch profile provisioned by Terraform"
  display_name   = "ESXi Uplink Profile"
  transport_vlan = 7
  overlay_encap  = "GENEVE"
  teaming {
    active {
      uplink_name = "uplink-1"
      uplink_type = "PNIC"
    }
    active {
      uplink_name = "uplink-2"
      uplink_type = "PNIC"
    }
    policy = "LOADBALANCE_SRCID"
  }
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm05" {
  display_name      = "amd-hwvm05"
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
      nsxt_policy_uplink_host_switch_profile.host_transport_node_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = nsxt_policy_ip_pool.host_transport_node_ip_pool.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan-tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay-tz.path
    }
    uplink {
      uplink_name     = "uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm06" {
  display_name      = "amd-hwvm06"
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
      nsxt_policy_uplink_host_switch_profile.host_transport_node_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = nsxt_policy_ip_pool.host_transport_node_ip_pool.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan-tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay-tz.path
    }
    uplink {
      uplink_name     = "uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm07" {
  display_name      = "amd-hwvm07"
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
      nsxt_policy_uplink_host_switch_profile.host_transport_node_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = nsxt_policy_ip_pool.host_transport_node_ip_pool.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan-tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay-tz.path
    }
    uplink {
      uplink_name     = "uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

resource "nsxt_policy_host_transport_node" "amd-hwvm08" {
  display_name      = "amd-hwvm08"
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
      nsxt_policy_uplink_host_switch_profile.host_transport_node_switch_profile.path,
      "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = nsxt_policy_ip_pool.host_transport_node_ip_pool.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan-tz.path
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay-tz.path
    }
    uplink {
      uplink_name     = "uplink-1"
      vds_uplink_name = "Uplink 1"
    }
    uplink {
      uplink_name     = "uplink-2"
      vds_uplink_name = "Uplink 2"
    }
  }
  tag {
    scope = "app"
    tag   = "web"
  }
}

// NOT READY YET
# resource "nsxt_policy_host_transport_node_collection" "amd-vmcl02" {
#   display_name                = "amd-vmcl02"
#   compute_collection_id       = vsphere_compute_cluster.cl02.id
#   transport_node_profile_path = "/infra/host-switch-profiles/0de8282e-7385-4e8e-a905-0c11960db728"
#   tag {
#     scope = "color"
#     tag   = "blue"
#   }
# }

resource "nsxt_policy_ip_pool" "ip_pool" {
  description  = "ip_pool provisioned by Terraform"
  display_name = "NSX-Edge-TEP-IP-Pool"
  tag {
    scope = "color"
    tag   = "blue"
  }
}

resource "nsxt_policy_ip_pool_static_subnet" "static_subnet1" {
  display_name = "static-subnet1"
  pool_path    = nsxt_policy_ip_pool.ip_pool.path
  cidr         = "10.0.3.64/26"
  gateway      = "10.0.3.65"
  dns_nameservers = [
    "10.0.3.65"
  ]
  allocation_range {
    start = "10.0.3.66"
    end   = "10.0.3.126"
  }
}

// Annoyed this isn't a policy resource
resource "nsxt_transport_node" "edge_node1" {
  display_name = "amd-nxed01"
  description  = "Terraform-deployed edge node"
  standard_host_switch {
    host_switch_profile = [
      nsxt_policy_uplink_host_switch_profile.uplink_host_switch_profile.id
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = "84b94d9b-eeec-4003-8784-94a33698fa56"
    }
    pnic {
      device_name = "fp-eth0"
      uplink_name = "uplink-1"
    }
    pnic {
      device_name = "fp-eth1"
      uplink_name = "uplink-2"
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.overlay-tz.id
    }
    transport_zone_endpoint {
      transport_zone = nsxt_policy_transport_zone.vlan-tz.id
    }
  }
  edge_node {
    deployment_config {
      form_factor = "SMALL"
      node_user_settings {
        cli_username  = var.nsx_transport_node_cli_username
        cli_password  = var.nsx_transport_node_cli_password
        root_password = var.nsx_transport_node_root_password
      }
      vm_deployment_config {
        compute_id = "resgroup-9"
        data_network_ids = [
          "dvportgroup-51",
          "dvportgroup-51"
        ]
        default_gateway_address = []
        ipv4_assignment_enabled = true
        management_network_id   = "dvportgroup-52"
        storage_id              = "datastore-29"
        vc_id                   = "900eeef9-018e-42da-9490-d0ebcad0600f"
        reservation_info {
          cpu_reservation_in_mhz        = 0
          cpu_reservation_in_shares     = "HIGH_PRIORITY"
          memory_reservation_percentage = 100
        }
      }
    }
    node_settings {
      hostname = "amd-nxed01.lab.amd-e.com"
      dns_servers = [
        "10.0.2.1"
      ]
      enable_ssh      = false
      enable_upt_mode = true
      ntp_servers = [
        "10.0.2.1"
      ]
      search_domains = [
        "lab.amd-e.com"
      ]
    }
  }
}

// Annoyed this isn't a policy resource
resource "nsxt_transport_node" "edge_node2" {
  display_name = "amd-nxed02"
  description  = "Terraform-deployed edge node"
  standard_host_switch {
    host_switch_profile = [
      "0c9ba813-35ee-4e1d-8bf6-6b6ac48c3cdf"
    ]
    ip_assignment {
      assigned_by_dhcp = false
      static_ip_pool   = "84b94d9b-eeec-4003-8784-94a33698fa56"
    }
    pnic {
      device_name = "fp-eth0"
      uplink_name = "uplink-1"
    }
    pnic {
      device_name = "fp-eth1"
      uplink_name = "uplink-2"
    }
    transport_zone_endpoint {
      transport_zone = "03ef8b4e-ac8d-407c-9d49-5dccfe5b6d03"
      transport_zone_profile = [
        "52035bb3-ab02-4a08-9884-18631312e50a"
      ]
    }
    transport_zone_endpoint {
      transport_zone = "b5c42a1d-1f81-414e-a41b-c12e61b639a0"
      transport_zone_profile = [
        "52035bb3-ab02-4a08-9884-18631312e50a"
      ]
    }
  }
  edge_node {
    deployment_config {
      form_factor = "SMALL"
      node_user_settings {
        cli_username  = var.nsx_transport_node_cli_username
        cli_password  = var.nsx_transport_node_cli_password
        root_password = var.nsx_transport_node_root_password
      }
      vm_deployment_config {
        compute_id = "resgroup-9"
        data_network_ids = [
          "dvportgroup-51",
          "dvportgroup-51"
        ]
        default_gateway_address = []
        ipv4_assignment_enabled = true
        management_network_id   = "dvportgroup-52"
        storage_id              = "datastore-29"
        vc_id                   = "900eeef9-018e-42da-9490-d0ebcad0600f"
        reservation_info {
          cpu_reservation_in_mhz        = 0
          cpu_reservation_in_shares     = "HIGH_PRIORITY"
          memory_reservation_percentage = 100
        }
      }
    }
    node_settings {
      hostname = "amd-nxed02.lab.amd-e.com"
      dns_servers = [
        "10.0.2.1"
      ]
      enable_ssh      = false
      enable_upt_mode = true
      ntp_servers = [
        "10.0.2.1"
      ]
      search_domains = [
        "lab.amd-e.com"
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
  failover_mode            = "PREEMPTIVE"
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

resource "nsxt_policy_tier0_gateway_interface" "if1" {
  display_name   = "tier0_gw_uplink01"
  description    = "connection for tier0_gw"
  type           = "EXTERNAL"
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/6592f789-16cb-407c-9b19-5edc7991f280/edge-nodes/4"
  gateway_path   = "/infra/tier-0s/amd-nxt0-1-"
  segment_path   = "/infra/segments/Edge_Uplink"
  subnets        = ["10.0.3.130/26"]
  ospf {
    area_path        = "/infra/tier-0s/amd-nxt0-1-/locale-services/default/ospf/areas/49370d63-16a5-4998-a168-8699df0025c2"
    bfd_profile_path = "/infra/bfd-profiles/Homelab"
    dead_interval    = 40
    enable_bfd       = true
    enabled          = true
    hello_interval   = 10
    network_type     = "BROADCAST"
  }
}

resource "nsxt_policy_tier0_gateway_interface" "if2" {
  display_name   = "tier0_gw_uplink02"
  description    = "connection for tier0_gw"
  type           = "EXTERNAL"
  edge_node_path = "/infra/sites/default/enforcement-points/default/edge-clusters/6592f789-16cb-407c-9b19-5edc7991f280/edge-nodes/3"
  gateway_path   = "/infra/tier-0s/amd-nxt0-1-"
  segment_path   = "/infra/segments/Edge_Uplink"
  subnets        = ["10.0.3.131/26"]
  ospf {
    area_path        = "/infra/tier-0s/amd-nxt0-1-/locale-services/default/ospf/areas/49370d63-16a5-4998-a168-8699df0025c2"
    bfd_profile_path = "/infra/bfd-profiles/Homelab"
    dead_interval    = 40
    enable_bfd       = true
    enabled          = true
    hello_interval   = 10
    network_type     = "BROADCAST"
  }
}

resource "nsxt_policy_tier1_gateway" "tier1_gw" {
  description  = "Tier-1 provisioned by Terraform"
  display_name = "tier1-gw1"
  depends_on = [
    nsxt_edge_cluster.edge_cluster
  ]
  edge_cluster_path         = data.nsxt_policy_edge_cluster.edge_cluster.path
  failover_mode             = "PREEMPTIVE"
  default_rule_logging      = "false"
  enable_firewall           = "true"
  enable_standby_relocation = "true"
  tier0_path                = nsxt_policy_tier0_gateway.tier0_gw.path
  dhcp_config_path          = "/infra/dhcp-server-configs/amd-nxdhcp01"
  route_advertisement_types = [
    "TIER1_DNS_FORWARDER_IP",
    "TIER1_IPSEC_LOCAL_ENDPOINT",
    "TIER1_LB_SNAT",
    "TIER1_LB_VIP",
    "TIER1_NAT",
    "TIER1_STATIC_ROUTES",
    "TIER1_CONNECTED"
  ]
  pool_allocation = "ROUTING"
  tag {
    scope = "color"
    tag   = "blue"
  }
}
