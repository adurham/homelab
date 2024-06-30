resource "nsxt_policy_fixed_segment" "tanium_clients_peering_test" {
  display_name      = "Tanium Clients - Peering Test"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.7.1/24"
    dhcp_ranges = ["172.16.7.2-172.16.7.254"]
    dhcp_v4_config {
      dns_servers = [
        "10.0.3.129"
      ]
      lease_time = 86400
    }
  }
}

resource "vsphere_folder" "tanium_clients_peering_test" {
  path          = "${vsphere_folder.tanium_qa_clients.path}/Peering Test"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

variable "instances" {
  description = "Number of instances"
  type        = number
  default     = 254
}

locals {
  network = { 
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = [for i in range(var.instances) : ""]
  }
}

module "homelab-tanium_clients_peering_test-debian_12" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 12"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-dbn12-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-debian_11" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 11"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-dbn11-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-debian_10" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 10"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-dbn10-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-ubuntu_22" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 22.04"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "normal"
  ram_size        = 4096
  io_share_level  = ["normal"]
  vmname          = "pt-ubnt22-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network         = local.network
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-ubuntu_20" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 20.04"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-ubnt20-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-ubuntu_18" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 18.04"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-ubnt18-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-rhel_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-rhel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-rhel_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-rhel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-rhel_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-rhel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-rhel_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-rhel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-oracle_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-oel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-oracle_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-oel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-oracle_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-oel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-oracle_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-oel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway = "172.16.7.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Rust"
}

module "homelab-tanium_clients_peering_test-windows_server_2022" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2022 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-wn2022-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.7.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Rust"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_peering_test-windows_server_2019" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2019 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-wn2019-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.7.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Rust"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_peering_test-windows_server_2016" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2016 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-wn2016-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.7.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Rust"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_peering_test-windows_server_2012r2" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_peering_test,
    vsphere_folder.tanium_clients_peering_test
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2012 R2 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_peering_test.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "pt-wn2012-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_peering_test.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.7.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Rust"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}
