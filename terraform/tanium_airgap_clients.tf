resource "vsphere_folder" "tanium_airgap_clients" {
  path          = "${vsphere_folder.tanium_airgap.path}/Clients"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_airgap_clients-debian_12" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Debian Linux 12"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-dbn12-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-debian_11" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Debian Linux 11"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-dbn11-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-debian_10" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Debian Linux 10"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-dbn10-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-ubuntu_22" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-ubnt22-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-ubuntu_20" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 20.04"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-ubnt20-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-ubuntu_18" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 18.04"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-ubnt18-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-rhel_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "RedHat Enterprise Linux 9"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-rhel9-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-rhel_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "RedHat Enterprise Linux 8"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-rhel8-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-rhel_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "RedHat Enterprise Linux 7"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-rhel7-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-rhel_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "RedHat Enterprise Linux 6"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-rhel6-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-oracle_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 9"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-oel9-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-oracle_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 8"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-oel8-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-oracle_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 7"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-oel7-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-oracle_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 6"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-oel6-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway = "172.16.6.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_airgap_clients-windows_server_2022" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2022 Datacenter"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-wn2022-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway        = "172.16.6.1"
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vSphere Rust"
  is_windows_image = true
  local_adminpass  = var.win_local_adminpass
}

module "homelab-tanium_airgap_clients-windows_server_2019" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2019 Datacenter"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-wn2019-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway        = "172.16.6.1"
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vSphere Rust"
  is_windows_image = true
  local_adminpass  = var.win_local_adminpass
}

module "homelab-tanium_airgap_clients-windows_server_2016" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2016 Datacenter"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-wn2016-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway        = "172.16.6.1"
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vSphere Rust"
  is_windows_image = true
  local_adminpass  = var.win_local_adminpass
}

module "homelab-tanium_airgap_clients-windows_server_2012r2" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_airgap,
    vsphere_folder.tanium_airgap_clients
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Windows Server 2012 R2 Datacenter"
  vmfolder   = vsphere_folder.tanium_airgap_clients.path
  instances  = 0
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tnag-wn2012-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_airgap.display_name}" = ["", ""]
  }
  vmgateway        = "172.16.6.1"
  dc               = vsphere_datacenter.Homelab.name
  datastore        = "vSphere Rust"
  is_windows_image = true
  local_adminpass  = var.win_local_adminpass
}
