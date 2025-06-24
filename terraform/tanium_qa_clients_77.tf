# resource "nsxt_policy_fixed_segment" "tanium_clients_77" {
#   display_name      = "Tanium Clients - 7.7"
#   description       = "Terraform provisioned Segment"
#   connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
#   subnet {
#     cidr        = "172.16.7.1/24"
#     dhcp_ranges = ["172.16.7.2-172.16.7.254"]
#     dhcp_v4_config {
#       dns_servers = var.dns_servers
#       lease_time  = var.lease_time
#     }
#   }
# }

resource "vsphere_folder" "tanium_clients_77" {
  path          = "${vsphere_folder.tanium_qa_clients.path}/7.7"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# module "homelab-tanium_clients_77-debian_12" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Debian Linux 12"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-dbn12-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-debian_11" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Debian Linux 11"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-dbn11-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-debian_10" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Debian Linux 10"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-dbn10-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-ubuntu_22" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Ubuntu Linux 22.04"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-ubnt22-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-ubuntu_20" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Ubuntu Linux 20.04"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-ubnt20-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-ubuntu_18" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Ubuntu Linux 18.04"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-ubnt18-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-rhel_9" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "RedHat Enterprise Linux 9"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-rhel9-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-rhel_8" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "RedHat Enterprise Linux 8"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-rhel8-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-rhel_7" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "RedHat Enterprise Linux 7"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-rhel7-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-rhel_6" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "RedHat Enterprise Linux 6"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-rhel6-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-oracle_9" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Oracle Linux 9"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-oel9-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-oracle_8" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Oracle Linux 8"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-oel8-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-oracle_7" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Oracle Linux 7"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-oel7-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-oracle_6" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Oracle Linux 6"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-oel6-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   domain          = var.domain
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway = "172.16.7.1"
#   dc        = vsphere_datacenter.Homelab.name
#   datastore = "vSphere Flash"
# }

# module "homelab-tanium_clients_77-windows_server_2022" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Windows Server 2022 Datacenter"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-wn2022-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway             = "172.16.7.1"
#   dc                    = vsphere_datacenter.Homelab.name
#   datastore             = "vSphere Flash"
#   is_windows_image      = true
#   windomain             = var.domain
#   domain_admin_user     = var.domainuser
#   domain_admin_password = var.domainpass
# }

# module "homelab-tanium_clients_77-windows_server_2019" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Windows Server 2019 Datacenter"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-wn2019-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway             = "172.16.7.1"
#   dc                    = vsphere_datacenter.Homelab.name
#   datastore             = "vSphere Flash"
#   is_windows_image      = true
#   windomain             = var.domain
#   domain_admin_user     = var.domainuser
#   domain_admin_password = var.domainpass
# }

# module "homelab-tanium_clients_77-windows_server_2016" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Windows Server 2016 Datacenter"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-wn2016-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway             = "172.16.7.1"
#   dc                    = vsphere_datacenter.Homelab.name
#   datastore             = "vSphere Flash"
#   is_windows_image      = true
#   windomain             = var.domain
#   domain_admin_user     = var.domainuser
#   domain_admin_password = var.domainpass
# }

# module "homelab-tanium_clients_77-windows_server_2012r2" {
#   depends_on = [
#     nsxt_policy_fixed_segment.tanium_clients_77,
#     vsphere_folder.tanium_clients_77
#   ]
#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Windows Server 2012 R2 Datacenter"
#   vmfolder        = vsphere_folder.tanium_clients_77.path
#   instances       = 1
#   cpu_number      = local.low_resource_vm_specs.cpu_number
#   cpu_share_level = local.low_resource_vm_specs.cpu_share_level
#   ram_size        = local.low_resource_vm_specs.ram_size
#   io_share_level  = local.low_resource_vm_specs.io_share_level
#   vmname          = "tn77-wn2012-"
#   vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
#   network = {
#     "${nsxt_policy_fixed_segment.tanium_clients_77.display_name}" = ["", ""]
#   }
#   vmgateway             = "172.16.7.1"
#   dc                    = vsphere_datacenter.Homelab.name
#   datastore             = "vSphere Flash"
#   is_windows_image      = true
#   windomain             = var.domain
#   domain_admin_user     = var.domainuser
#   domain_admin_password = var.domainpass
# }
