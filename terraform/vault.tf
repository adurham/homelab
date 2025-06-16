# Define a fixed segment for Vault
resource "nsxt_policy_fixed_segment" "vault" {
  display_name      = "Vault"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path

  subnet {
    cidr = local.services.vault.cidr
    dhcp_v4_config {
      dns_servers = local.dns_servers
      lease_time  = local.lease_time
    }
  }
}

# Create a VM folder for Vault
resource "vsphere_folder" "vault" {
  path          = "Vault"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# # Deploy the Vault server using a module
# module "homelab-vault_server" {
#   depends_on = [
#     nsxt_policy_fixed_segment.vault,
#     vsphere_folder.vault
#   ]

#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Ubuntu Linux 22.04"
#   vmfolder        = vsphere_folder.vault.path
#   instances       = var.vault_instances
#   cpu_number      = local.vault_resource_vm_specs.cpu_number
#   cpu_share_level = local.vault_resource_vm_specs.cpu_share_level
#   ram_size        = local.vault_resource_vm_specs.ram_size
#   io_share_level  = local.vault_resource_vm_specs.io_share_level
#   vmname          = "amd-lxvlt"
#   vmrp            = local.cl02_resource_pool
#   domain          = var.domain

#   network = {
#     (nsxt_policy_fixed_segment.vault.display_name) = local.vault_ips
#   }

#   ipv4submask     = local.vault_netmask_cidr
#   vmgateway       = local.vault_gateway
#   dns_server_list = local.dns_servers
#   dc              = local.vsphere_datacenter
#   datastore       = local.datastore_vsan
# }

# # Output the segment path for further use or debugging
# output "vault_segment_path" {
#   value = nsxt_policy_fixed_segment.vault.path
# }

# # Output the folder path for further use or debugging
# output "vault_folder_path" {
#   value = vsphere_folder.vault.path
# }
