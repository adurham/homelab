resource "nsxt_policy_fixed_segment" "tanium_airgap" {
  display_name      = "Tanium Airgap"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.6.1/24"
    # dhcp_ranges = ["172.16.6.10-172.16.6.254"]
    # dhcp_v4_config {
    #   dns_servers = var.dns_servers
    #   lease_time  = var.lease_time
    # }
  }
}

resource "vsphere_folder" "tanium_airgap" {
  path          = "${vsphere_folder.tanium.path}/Airgap"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

resource "vsphere_folder" "tanium_airgap_tanos" {
  path          = "${vsphere_folder.tanium_airgap.path}/TanOS"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "TanOS 1.8.1.0165 - Dev"
  vmfolder   = vsphere_folder.tanium_airgap_tanos.path
  instances  = 2
  cpu_number = 4
  ram_size   = 16384
  vmname     = "amd-agts"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.3", "172.16.6.4"]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

module "homelab-tanium_module_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "TanOS 1.8.1.0165 - Dev"
  vmfolder   = vsphere_folder.tanium_airgap_tanos.path
  instances  = 2
  cpu_number = 4
  ram_size   = 16384
  vmname     = "amd-agtms"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.5", "172.16.6.6"]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

module "homelab-tanium_zone_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "TanOS 1.8.1.0165 - Dev"
  vmfolder   = vsphere_folder.tanium_airgap_tanos.path
  instances  = 2
  cpu_number = 4
  ram_size   = 16384
  vmname     = "amd-agzs"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.7", "172.16.6.8"]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

resource "vsphere_folder" "tanium_airgap_windows" {
  path          = "${vsphere_folder.tanium_airgap.path}/Windows"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-windows_tanium_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.tanium_airgap_windows.path
  instances    = 2
  cpu_number   = 4
  ram_size     = 32768
  disk_size_gb = ["512"]
  vmname       = "amd-agwts"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.9", "172.16.6.10"]
  }
  vmgateway        = "172.16.6.1"
  dns_server_list  = ["10.0.3.129"]
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vsanDatastore"
  is_windows_image = true
}

module "homelab-windows_tanium_module_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.tanium_airgap_windows.path
  instances    = 1
  cpu_number   = 8
  ram_size     = 32768
  disk_size_gb = ["512"]
  vmname       = "amd-agwtms"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.11"]
  }
  vmgateway        = "172.16.6.1"
  dns_server_list  = ["10.0.3.129"]
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vsanDatastore"
  is_windows_image = true
}

module "homelab-windows_tanium_zone_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.tanium_airgap_windows.path
  instances    = 2
  cpu_number   = 4
  ram_size     = 16384
  disk_size_gb = ["240"]
  vmname       = "amd-agwzs"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.13", "172.16.6.14"]
  }
  vmgateway        = "172.16.6.1"
  dns_server_list  = ["10.0.3.129"]
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vsanDatastore"
  is_windows_image = true
}

module "homelab-windows_tanium_sql_server_airgap" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.tanium_airgap_windows.path
  instances    = 1
  cpu_number   = 4
  ram_size     = 16384
  disk_size_gb = ["240"]
  vmname       = "amd-agwtsql"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["172.16.6.15"]
  }
  vmgateway        = "172.16.6.1"
  dns_server_list  = ["10.0.3.129"]
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vsanDatastore"
  is_windows_image = true
}
