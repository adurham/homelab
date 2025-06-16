# Define a fixed segment for Consul
resource "nsxt_policy_fixed_segment" "consul" {
  display_name      = "Consul"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path

  subnet {
    cidr = local.services.consul.cidr
    dhcp_v4_config {
      dns_servers = local.dns_servers
      lease_time  = local.lease_time
    }
  }
}

# Create a VM folder for Consul
resource "vsphere_folder" "consul" {
  path          = "Consul"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# # Deploy the Consul server using a module
# module "homelab-consul_server" {
#   depends_on = [
#     nsxt_policy_fixed_segment.consul,
#     vsphere_folder.consul
#   ]

#   source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
#   vmtemp          = "Ubuntu Linux 22.04"
#   vmfolder        = vsphere_folder.consul.path
#   instances       = var.consul_instances
#   cpu_number      = local.consul_resource_vm_specs.cpu_number
#   cpu_share_level = local.consul_resource_vm_specs.cpu_share_level
#   ram_size        = local.consul_resource_vm_specs.ram_size
#   io_share_level  = local.consul_resource_vm_specs.io_share_level
#   vmname          = "amd-lxcnsl"
#   vmrp            = local.cl02_resource_pool
#   domain          = var.domain

#   network = {
#     (nsxt_policy_fixed_segment.consul.display_name) = local.consul_ips
#   }

#   ipv4submask     = local.consul_netmask_cidr
#   vmgateway       = local.consul_gateway
#   dns_server_list = local.dns_servers
#   dc              = local.vsphere_datacenter
#   datastore       = local.datastore_vsan
# }

# # Output the segment path for further use or debugging
# output "consul_segment_path" {
#   value = nsxt_policy_fixed_segment.consul.path
# }

# # Output the folder path for further use or debugging
# output "consul_folder_path" {
#   value = vsphere_folder.consul.path
# }
