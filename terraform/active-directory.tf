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

resource "vsphere_folder" "active_directory" {
  path          = "Active Directory"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

resource "vsphere_folder" "active_directory_federation_services" {
  path          = "ADFS"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

resource "vsphere_folder" "active_directory_certificate_authority" {
  path          = "ADCA"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-active_directory" {
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory.path
  instances       = var.ad_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnad"
  vmrp            = local.cl02_resource_pool
  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.active_directory_ips
  }
  vmgateway        = local.active_directory_vmgw
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}


module "homelab-active_directory_federation_services" {
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory_federation_services.path
  instances       = var.ad_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnadfs"
  vmrp            = local.cl02_resource_pool
  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.federation_services_ips
  }
  vmgateway        = local.active_directory_vmgw
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}

module "homelab-active_directory_certificate_authority" {
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = local.ws22dc_template
  vmfolder        = vsphere_folder.active_directory_certificate_authority.path
  instances       = var.ad_instances
  cpu_number      = local.active_directory_resource_vm_specs.cpu_number
  cpu_share_level = local.active_directory_resource_vm_specs.cpu_share_level
  ram_size        = local.active_directory_resource_vm_specs.ram_size
  io_share_level  = local.active_directory_resource_vm_specs.io_share_level
  vmname          = "amd-wnadca"
  vmrp            = local.cl02_resource_pool
  network = {
    (nsxt_policy_fixed_segment.active_directory.display_name) = local.certificate_authority_ips
  }
  vmgateway        = local.active_directory_vmgw
  dc               = local.vsphere_datacenter
  datastore        = local.datastore_vsan
  is_windows_image = true
}
