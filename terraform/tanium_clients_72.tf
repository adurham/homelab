resource "nsxt_policy_fixed_segment" "tanium_clients_72" {
  display_name      = "Tanium Clients - 7.2"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.3.1/24"
    dhcp_ranges = ["172.16.3.2-172.16.3.254"]
    dhcp_v4_config {
      dns_servers = [
        "10.0.3.129"
      ]
      lease_time = 86400
    }
  }
}

resource "vsphere_folder" "tanium_clients_72" {
  path          = "${vsphere_folder.tanium_qa_clients.path}/7.2"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_clients_72-debian_12" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 12"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-dbn12-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-debian_11" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 11"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-dbn11-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-debian_10" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Debian Linux 10"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 0
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-dbn10-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-ubuntu_22" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 22.04"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-ubnt22-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-ubuntu_20" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 20.04"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-ubnt20-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-ubuntu_18" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Ubuntu Linux 18.04"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-ubnt18-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-rhel_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-rhel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-rhel_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-rhel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-rhel_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-rhel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-rhel_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "RedHat Enterprise Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-rhel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-oracle_9" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 9"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-oel9-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-oracle_8" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 8"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-oel8-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-oracle_7" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 7"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-oel7-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-oracle_6" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Oracle Linux 6"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-oel6-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  domain          = var.domain
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway = "172.16.3.1"
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vSphere Flash"
}

module "homelab-tanium_clients_72-windows_server_2022" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2022 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-wn2022-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.3.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_72-windows_server_2019" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2019 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-wn2019-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.3.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_72-windows_server_2016" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2016 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-wn2016-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.3.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}

module "homelab-tanium_clients_72-windows_server_2012r2" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium_clients_72,
    vsphere_folder.tanium_clients_72
  ]
  source          = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp          = "Windows Server 2012 R2 Datacenter"
  vmfolder        = vsphere_folder.tanium_clients_72.path
  instances       = 1
  cpu_number      = 2
  cpu_share_level = "low"
  ram_size        = 4096
  io_share_level  = ["low"]
  vmname          = "tn72-wn2012-"
  vmrp            = "${vsphere_compute_cluster.cl01.name}/Resources"
  network = {
    "${nsxt_policy_fixed_segment.tanium_clients_72.display_name}" = ["", ""]
  }
  vmgateway             = "172.16.3.1"
  dc                    = vsphere_datacenter.Homelab.name
  datastore             = "vSphere Flash"
  is_windows_image      = true
  windomain             = var.domain
  domain_admin_user     = var.domainuser
  domain_admin_password = var.domainpass
}
