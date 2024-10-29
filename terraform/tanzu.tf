# resource "nsxt_policy_fixed_segment" "tanzu_management" {
#   display_name      = "Tanzu Management"
#   description       = "Terraform provisioned Segment"
#   connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
#   subnet {
#     cidr        = "172.16.0.177/28"
#     dhcp_ranges = ["172.16.0.179-172.16.0.190"]
#     dhcp_v4_config {
#       dns_servers = var.dns_servers
#       lease_time  = var.lease_time
#     }
#   }
# }

# # resource "nsxt_policy_fixed_segment" "tanzu_ingress" {
# #   display_name        = "Tanzu Ingress"
# #   description         = "Terraform provisioned Segment"
# #   connectivity_path   = nsxt_policy_tier1_gateway.tier1_gw.path
# #   subnet {
# #     cidr = "172.17.0.1/21"
# #     dhcp_v4_config {
# #       dns_servers = [
# #         "10.0.3.129"
# #       ]
# #       lease_time = 86400
# #     }
# #   }
# # }

# # resource "nsxt_policy_fixed_segment" "tanzu_egress" {
# #   display_name        = "Tanzu Egress"
# #   description         = "Terraform provisioned Segment"
# #   connectivity_path   = nsxt_policy_tier1_gateway.tier1_gw.path
# #   subnet {
# #     cidr = "172.17.8.1/21"
# #     dhcp_v4_config {
# #       dns_servers = [
# #         "10.0.3.129"
# #       ]
# #       lease_time = 86400
# #     }
# #   }
# # }
