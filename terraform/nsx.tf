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

}

data "nsxt_policy_edge_cluster" "EC" {
  display_name = "amd-nxedcl01"
}

resource "nsxt_policy_tier1_gateway" "tier1_gw" {
  description               = "Tier-1 provisioned by Terraform"
  display_name              = "tier1-gw1"
  edge_cluster_path         = data.nsxt_policy_edge_cluster.EC.path
  failover_mode             = "NON_PREEMPTIVE"
  default_rule_logging      = "false"
  enable_firewall           = "true"
  enable_standby_relocation = "false"
  tier0_path                = nsxt_policy_tier0_gateway.tier0_gw.path
  route_advertisement_types = [
    "TIER1_DNS_FORWARDER_IP",
    "TIER1_IPSEC_LOCAL_ENDPOINT",
    "TIER1_LB_SNAT",
    "TIER1_LB_VIP",
    "TIER1_NAT",
    "TIER1_STATIC_ROUTES",
    "TIER1_CONNECTED"
  ]
  pool_allocation           = "ROUTING"

  tag {
    scope = "color"
    tag   = "blue"
  }

  route_advertisement_rule {
    name                      = "rule1"
    action                    = "DENY"
    subnets                   = ["20.0.0.0/24", "21.0.0.0/24"]
    prefix_operator           = "GE"
    route_advertisement_types = ["TIER1_CONNECTED"]
  }
}