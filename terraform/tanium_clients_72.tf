# resource "nsxt_policy_fixed_segment" "tanium_clients-72" {
#   display_name      = "Homelab - Tanium"
#   description       = "Terraform provisioned Segment"
#   connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
#   subnet {
#     cidr        = "172.16.1.1/25"
#     dhcp_v4_config {
#         dns_servers = [
#             "10.0.3.129"
#         ]
#         lease_time = 86400
#     }
#   }
# }

# resource "vsphere_folder" "tanium_clients-72" {
#   path          = "Tanium"
#   type          = "vm"
#   datacenter_id = vsphere_datacenter.Homelab.moid
# }

# module "homelab-tanium_clients-72_linux" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium,
#     vsphere_folder.tanium
#   ]
#   source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp    = "TanOS 1.8.1.0165 - Dev"
#   vmfolder = vsphere_folder.tanium.path
#   instances = 0
#   cpu_number = 4
#   ram_size = 16384
#   vmname    = "amd-lxts"
#   vmrp      = "${vsphere_compute_cluster.cl02.name}/Resources"
#   domain = "lab.amd-e.com"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.3", "172.16.1.4"]
#   }
#   vmgateway = "172.16.1.1"
#   dc        = "${vsphere_datacenter.Homelab.name}"
#   datastore = "vsanDatastore"
# }

# module "homelab-tanium_clients-72_windows" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium,
#     vsphere_folder.windows_tanium
#   ]
#   source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp    = "Windows Server 2022 Datacenter"
#   vmfolder = vsphere_folder.windows_tanium.path
#   instances = 0
#   cpu_number = 4
#   ram_size = 16384
#   vmname    = "amd-wntsql"
#   vmrp      = "${vsphere_compute_cluster.cl02.name}/Resources"
#   domain = "lab.amd-e.com"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.12"]
#   }
#   vmgateway = "172.16.1.1"
#   dc        = "${vsphere_datacenter.Homelab.name}"
#   datastore = "vsanDatastore"
#   is_windows_image = true
# }
