resource "nsxt_policy_fixed_segment" "active_directory" {
  display_name      = "Homelab - Active Directory"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.0.1/25"
    dhcp_v4_config {
        dns_servers = [
            "10.0.3.129"
        ]
        lease_time = 86400
    }
  }
}

// TODO - Add VMs