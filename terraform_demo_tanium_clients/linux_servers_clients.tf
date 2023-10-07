module "demo_alma8_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Alma Linux 8"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-alm8"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_alma9_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Alma Linux 9"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-alm9"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_debian10_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Debian 10"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-deb10"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_debian11_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Debian 11"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-deb11"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_debian12_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Debian 12"
  instances    = 0
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-deb12"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_opensuse12_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "OpenSUSE 12"
  instances    = 0
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-sus12"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_opensuse15_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "OpenSUSE 15"
  instances    = 0
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-sus15"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_oracle7_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Oracle Linux 7"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ocl7"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_oracle8_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Oracle Linux 8"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ocl8"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_oracle9_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Oracle Linux 9"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ocl9"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_rhel7_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "RedHat Enterprise Linux 7"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-rhl7"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_rhel8_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "RedHat Enterprise Linux 8"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-rhl8"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_rhel9_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "RedHat Enterprise Linux 9"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-rhl9"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_rocky8_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Rocky Linux 8"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-rky8"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_rocky9_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Rocky Linux 9"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-rky9"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_suse12_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "SUSE Linux Enterprise 12"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-sle12"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_suse15_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "SUSE Linux Enterprise 15"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-sle15"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_ubuntu1804_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Ubuntu Server 18.04 LTS"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ubn18"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_ubuntu2004_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Ubuntu Server 20.04 LTS"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ubn20"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_ubuntu2204_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Ubuntu Server 22.04 LTS"
  instances    = 5
  vmname       = "dmo-lxsrv"
  vmnameformat = "%01d-ubn22"
  domain       = "lab.amd-e.com"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore  = "vSphere Rust"
  dns_server_list = ["10.0.4.1"]
  vmgateway       = "10.0.4.1"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}
