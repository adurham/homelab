resource "nsxt_policy_fixed_segment" "tanium" {
  display_name      = "Tanium"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr = "172.16.1.1/25"
    dhcp_v4_config {
      dns_servers = var.dns_servers
      lease_time  = var.lease_time
    }
  }
}

resource "vsphere_folder" "tanium" {
  path          = "Tanium"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.tanium
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "TanOS 1.8.1.0165 - Dev"
  vmfolder     = vsphere_folder.tanium.path
  instances    = 2
  cpu_number   = 4
  ram_size     = 32768
  disk_size_gb = ["750"]
  vmname       = "amd-lxts"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.3", "172.16.1.4"]
  }
  vmgateway = "172.16.1.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

module "homelab-tanium_module_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.tanium
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "TanOS 1.8.1.0165 - Dev"
  vmfolder   = vsphere_folder.tanium.path
  instances  = 2
  cpu_number = 8
  ram_size   = 32768
  vmname     = "amd-lxtms"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.5", "172.16.1.6"]
  }
  vmgateway = "172.16.1.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

module "homelab-tanium_zone_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.tanium
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "TanOS 1.8.1.0165 - Dev"
  vmfolder   = vsphere_folder.tanium.path
  instances  = 2
  cpu_number = 4
  ram_size   = 8192
  vmname     = "amd-lxzs"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.7", "172.16.1.8"]
  }
  vmgateway = "172.16.1.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}

resource "vsphere_folder" "windows_tanium" {
  path          = "${vsphere_folder.tanium.path}/Windows TS"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-windows_tanium_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.windows_tanium
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.windows_tanium.path
  instances    = 2
  cpu_number   = 4
  ram_size     = 32768
  disk_size_gb = ["512"]
  vmname       = "amd-wnts"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.9", "172.16.1.10"]
  }
  vmgateway             = "172.16.1.1"
  dns_server_list       = ["10.0.3.129"]
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vsanDatastore"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-windows_tanium_module_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.windows_tanium
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.windows_tanium.path
  instances    = 1
  cpu_number   = 8
  ram_size     = 32768
  disk_size_gb = ["512"]
  vmname       = "amd-wntms"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.11"]
  }
  vmgateway             = "172.16.1.1"
  dns_server_list       = ["10.0.3.129"]
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vsanDatastore"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-windows_tanium_zone_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.windows_tanium
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.windows_tanium.path
  instances    = 2
  cpu_number   = 4
  ram_size     = 16384
  disk_size_gb = ["240"]
  vmname       = "amd-wnzs"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain       = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.13", "172.16.1.14"]
  }
  vmgateway             = "172.16.1.1"
  dns_server_list       = ["10.0.3.129"]
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vsanDatastore"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-windows_tanium_sql_server" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.windows_tanium
  ]
  source       = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp       = "Windows Server 2022 Datacenter"
  vmfolder     = vsphere_folder.windows_tanium.path
  instances    = 1
  cpu_number   = 4
  ram_size     = 16384
  disk_size_gb = ["240"]
  vmname       = "amd-wntsql"
  vmrp         = "${vsphere_compute_cluster.cl02.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.15"]
  }
  vmgateway             = "172.16.1.1"
  dns_server_list       = ["10.0.3.129"]
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vsanDatastore"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}
