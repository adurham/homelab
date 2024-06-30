resource "nsxt_policy_fixed_segment" "tanium_clients_74" {
  display_name      = "Tanium Clients - 7.4"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.4.1/24"
    dhcp_ranges = ["172.16.4.2-172.16.4.254"]
    dhcp_v4_config {
      dns_servers = var.dns_servers
      lease_time  = var.lease_time
    }
  }
}

resource "vsphere_folder" "tanium_clients_74" {
  path          = "${vsphere_folder.tanium_qa_clients.path}/7.4"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_clients_74-debian_12" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 12"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-dbn12-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-debian_11" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 11"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-dbn11-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-debian_10" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 10"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-dbn10-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-ubuntu_22" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 22.04"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-ubnt22-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-ubuntu_20" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 20.04"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-ubnt20-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-ubuntu_18" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 18.04"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-ubnt18-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-rhel_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-rhel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-rhel_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-rhel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-rhel_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-rhel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-rhel_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-rhel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-oracle_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-oel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-oracle_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-oel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-oracle_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-oel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-oracle_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-oel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway = "172.16.4.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_74-windows_server_2022" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2022 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-wn2022-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.4.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_74-windows_server_2019" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2019 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-wn2019-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.4.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_74-windows_server_2016" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2016 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-wn2016-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.4.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_74-windows_server_2012r2" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_74,
    vsphere_folder.tanium_clients_74
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2012 R2 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_74.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn74-wn2012-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_74.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.4.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}
