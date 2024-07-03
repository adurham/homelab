# Define a fixed segment for Active Directory
resource "nsxt_policy_fixed_segment" "active_directory" {
  display_name        = "Active Directory"
  description         = "Terraform provisioned Segment"
  connectivity_path   = nsxt_policy_tier1_gateway.tier1_gw.path
  overlay_id          = 0
  replication_mode    = "MTEP"
  transport_zone_path = nsxt_policy_transport_zone.overlay_tz.path

  subnet {
    cidr = local.active_directory_cidr
    dhcp_v4_config {
      dns_servers = local.dns_servers
      lease_time  = local.lease_time
    }
  }
}

# Create a VM folder for Active Directory
resource "vsphere_folder" "active_directory" {
  path          = "Active Directory"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# Create a VM folder for Active Directory Federation Services (ADFS)
resource "vsphere_folder" "active_directory_federation_services" {
  path          = "ADFS"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# Create a VM folder for Active Directory Certificate Authority (ADCA)
resource "vsphere_folder" "active_directory_certificate_authority" {
  path          = "ADCA"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

# Deploy the Active Directory server using a module
module "homelab-active_directory" {
  depends_on = [
    nsxt_policy_fixed_segment.active_directory,
    vsphere_folder.active_directory
  ]

  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory.path
  instances       = var.active_directory_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnad"
  vmrp            = local.cl02_resource_pool

  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.active_directory_ips
  }

  vmgateway        = local.active_directory_gateway
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}

# Deploy the Active Directory Federation Services (ADFS) server using a module
module "homelab-active_directory_federation_services" {
  depends_on = [
    nsxt_policy_fixed_segment.active_directory,
    vsphere_folder.active_directory_federation_services
  ]

  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory_federation_services.path
  instances       = var.active_directory_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnadfs"
  vmrp            = local.cl02_resource_pool

  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.federation_services_ips
  }

  vmgateway        = local.active_directory_gateway
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}

# Deploy the Active Directory Certificate Authority (ADCA) server using a module
module "homelab-active_directory_certificate_authority" {
  depends_on = [
    nsxt_policy_fixed_segment.active_directory,
    vsphere_folder.active_directory_certificate_authority
  ]

  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory_certificate_authority.path
  instances       = var.active_directory_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnadca"
  vmrp            = local.cl02_resource_pool

  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.certificate_authority_ips
  }

  vmgateway        = local.active_directory_gateway
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}

# Output the segment path for further use or debugging
output "active_directory_segment_path" {
  value = nsxt_policy_fixed_segment.active_directory.path
}

# Output the folder path for Active Directory for further use or debugging
output "active_directory_folder_path" {
  value = vsphere_folder.active_directory.path
}

# Output the folder path for Active Directory Federation Services (ADFS) for further use or debugging
output "active_directory_federation_services_folder_path" {
  value = vsphere_folder.active_directory_federation_services.path
}

# Output the folder path for Active Directory Certificate Authority (ADCA) for further use or debugging
output "active_directory_certificate_authority_folder_path" {
  value = vsphere_folder.active_directory_certificate_authority.path
}
