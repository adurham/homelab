resource "nsxt_policy_fixed_segment" "active_directory" {
  display_name        = "Active Directory"
  description         = "Terraform provisioned Segment"
  connectivity_path   = nsxt_policy_tier1_gateway.tier1_gw.path
  overlay_id          = 0
  replication_mode    = "MTEP"
  transport_zone_path = nsxt_policy_transport_zone.overlay_tz.path
  subnet {
    cidr = "172.16.0.1/25"
    dhcp_v4_config {
      dns_servers = var.dns_servers
      lease_time  = var.lease_time
    }
  }
}

resource "vsphere_folder" "active_directory" {
  path          = "Active Directory"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-active_directory" {
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2022 Datacenter"
  vmfolder   = vsphere_folder.active_directory.path
  instances  = 3
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-wnad"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.active_directory.display_name}" = ["172.16.0.3", "172.16.0.4", "172.16.0.5"]
  }
  vmgateway        = "172.16.0.1"
  dc               = "Homelab"
  datastore        = "vsanDatastore"
  is_windows_image = true
}

resource "vsphere_folder" "active_directory_federation_services" {
  path          = "ADFS"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-active_directory_federation_services" {
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2022 Datacenter"
  vmfolder   = vsphere_folder.active_directory_federation_services.path
  instances  = 3
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-wnadfs"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.active_directory.display_name}" = ["172.16.0.7", "172.16.0.8", "172.16.0.9"]
  }
  vmgateway        = "172.16.0.1"
  dc               = "Homelab"
  datastore        = "vsanDatastore"
  is_windows_image = true
}

resource "vsphere_folder" "active_directory_certificate_authority" {
  path          = "ADCA"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-active_directory_certificate_authority" {
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2022 Datacenter"
  vmfolder   = vsphere_folder.active_directory_certificate_authority.path
  instances  = 3
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-wnadca"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.active_directory.display_name}" = ["172.16.0.9", "172.16.0.10", "172.16.0.11"]
  }
  vmgateway        = "172.16.0.1"
  dc               = "Homelab"
  datastore        = "vsanDatastore"
  is_windows_image = true
}
