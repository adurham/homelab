# Define a fixed segment for Keycloak
resource "nsxt_policy_fixed_segment" "keycloak" {
  display_name      = "Keycloak"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path

  subnet {
    cidr = local.keycloak_cidr
    dhcp_v4_config {
      dns_servers = local.dns_servers
      lease_time  = local.lease_time
    }
  }
}

# Create a VM folder for Keycloak
resource "vsphere_folder" "keycloak" {
  path          = "Keycloak"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# Deploy the Keycloak server using a module
module "homelab-keycloak_server" {
  depends_on = [
    nsxt_policy_fixed_segment.keycloak,
    vsphere_folder.keycloak
  ]

  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 22.04"
  vmfolder        = vsphere_folder.keycloak.path
  instances       = var.keycloak_instances
  cpu_number      = local.keycloak_resource_vm_specs.cpu_number
  cpu_share_level = local.keycloak_resource_vm_specs.cpu_share_level
  ram_size        = local.keycloak_resource_vm_specs.ram_size
  io_share_level  = local.keycloak_resource_vm_specs.io_share_level
  vmname          = "amd-lxkycl"
  vmrp            = local.cl02_resource_pool
  domain          = var.domain

  network = {
    (nsxt_policy_fixed_segment.keycloak.display_name) = local.keycloak_ips
  }

  ipv4submask     = local.keycloak_netmask_cidr
  vmgateway       = local.keycloak_gateway
  dns_server_list = local.dns_servers
  dc              = local.vsphere_datacenter
  datastore       = local.datastore_vsan
}

# Output the segment path for further use or debugging
output "keycloak_segment_path" {
  value = nsxt_policy_fixed_segment.keycloak.path
}

# Output the folder path for further use or debugging
output "keycloak_folder_path" {
  value = vsphere_folder.keycloak.path
}
