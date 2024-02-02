resource "nsxt_policy_fixed_segment" "tanium_clients_76" {
  display_name      = "Tanium Clients - 7.6"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.5.1/24"
    dhcp_ranges = ["172.16.5.2-172.16.5.254"]
    dhcp_v4_config {
      dns_servers = [
        "10.0.3.129"
      ]
      lease_time = 86400
    }
  }
}

resource "vsphere_folder" "tanium_clients_76" {
  path          = "${vsphere_folder.tanium_qa_clients.path}/7.6"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_clients_76-ubuntu_22" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-ubnt22-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-ubuntu_20" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 20.04"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-ubnt20-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-ubuntu_18" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 18.04"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-ubnt18-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-oracle_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 6"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-oel6-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-oracle_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 7"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-oel7-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-oracle_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 8"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-oel8-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-oracle_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Oracle Linux 9"
  vmfolder   = vsphere_folder.tanium_clients_76.path
  instances  = 2
  cpu_number = 2
  ram_size   = 4096
  vmname     = "tn76-oel9-"
  vmrp       = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["", ""]
  }
  vmgateway = "172.16.5.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_76-windows_server_2022" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "Windows Server 2022 Datacenter"
  vmfolder = vsphere_folder.tanium_clients_76.path
  instances = 2
  cpu_number = 2
  ram_size = 4096
  vmname    = "tn76-wn2022-"
  vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["",""]
  }
  vmgateway = "172.16.5.1"
  dc        = "${vsphere_datacenter.Homelab.name}"
  datastore = "vSphere Rust"
  is_windows_image = true
}

module "homelab-tanium_clients_76-windows_server_2019" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "Windows Server 2019 Datacenter"
  vmfolder = vsphere_folder.tanium_clients_76.path
  instances = 2
  cpu_number = 2
  ram_size = 4096
  vmname    = "tn76-wn2019-"
  vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["",""]
  }
  vmgateway = "172.16.5.1"
  dc        = "${vsphere_datacenter.Homelab.name}"
  datastore = "vSphere Rust"
  is_windows_image = true
}

module "homelab-tanium_clients_76-windows_server_2016" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "Windows Server 2016 Datacenter"
  vmfolder = vsphere_folder.tanium_clients_76.path
  instances = 2
  cpu_number = 2
  ram_size = 4096
  vmname    = "tn76-wn2016-"
  vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["",""]
  }
  vmgateway = "172.16.5.1"
  dc        = "${vsphere_datacenter.Homelab.name}"
  datastore = "vSphere Rust"
  is_windows_image = true
}

module "homelab-tanium_clients_76-windows_server_2012r2" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_76,
    vsphere_folder.tanium_clients_76
  ]
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "Windows Server 2012 R2 Datacenter"
  vmfolder = vsphere_folder.tanium_clients_76.path
  instances = 2
  cpu_number = 2
  ram_size = 4096
  vmname    = "tn76-wn2012-"
  vmrp      = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_76.display_name}" = ["",""]
  }
  vmgateway = "172.16.5.1"
  dc        = "${vsphere_datacenter.Homelab.name}"
  datastore = "vSphere Rust"
  is_windows_image = true
}
