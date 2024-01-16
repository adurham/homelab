# resource "nsxt_policy_fixed_segment" "tanium_clients_72" {
#   display_name      = "Homelab - Tanium Clients - 7.2"
#   description       = "Terraform provisioned Segment"
#   connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
#   subnet {
#     cidr        = "172.16.3.1/24"
#     dhcp_v4_config {
#         dns_servers = [
#             "10.0.3.129"
#         ]
#         lease_time = 86400
#     }
#   }
# }

# resource "vsphere_folder" "tanium_clients_72" {
#   path          = "Tanium/Clients/7.2"
#   type          = "vm"
#   datacenter_id = vsphere_datacenter.Homelab.moid
# }

# module "homelab-tanium_clients_72-ubuntu_22" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_72,
#     vsphere_folder.tanium_clients_72
#   ]
#   source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp    = "Ubuntu Linux 22.04"
#   vmfolder = vsphere_folder.tanium_clients_72.path
#   instances = 2
#   cpu_number = 2
#   ram_size = 4096
#   vmname    = "tn72-ubnt22-"
#   vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain = "lab.amd-e.com"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["",""]
#   }
#   vmgateway = "172.16.3.1"
#   dc        = "${vsphere_datacenter.Homelab.name}"
#   datastore = "vSphere Flash 1"
# }

# module "homelab-tanium_clients_72-windows_server_2022" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_72,
#     vsphere_folder.tanium_clients_72
#   ]
#   source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp    = "Windows Server 2022 Datacenter"
#   vmfolder = vsphere_folder.tanium_clients_72.path
#   instances = 2
#   cpu_number = 2
#   ram_size = 4096
#   vmname    = "tn72-wn2022-"
#   vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain = "lab.amd-e.com"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["",""]
#   }
#   vmgateway = "172.16.3.1"
#   dc        = "${vsphere_datacenter.Homelab.name}"
#   datastore = "vSphere Flash 1"
#   is_windows_image = true
# }
