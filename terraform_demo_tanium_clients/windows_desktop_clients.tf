module "demo_wn1015_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Windows Server 2012 R2"
  instances    = 5
  vmname       = "dmo-wndsk"
  vmnameformat = "%01d-2k15"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore             = "vSphere Rust"
  dns_server_list            = ["10.0.4.1"]
  vmgateway                  = "10.0.4.1"
  is_windows_image           = true
  local_adminpass            = var.win_local_adminpass
  workgroup                  = "local"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_wn1016_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Windows Server 2016"
  instances    = 5
  vmname       = "dmo-wndsk"
  vmnameformat = "%01d-2k16"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore             = "vSphere Rust"
  dns_server_list            = ["10.0.4.1"]
  vmgateway                  = "10.0.4.1"
  is_windows_image           = true
  local_adminpass            = var.win_local_adminpass
  workgroup                  = "local"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_wn1019_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Windows Server 2019"
  instances    = 5
  vmname       = "dmo-wndsk"
  vmnameformat = "%01d-2k19"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore             = "vSphere Rust"
  dns_server_list            = ["10.0.4.1"]
  vmgateway                  = "10.0.4.1"
  is_windows_image           = true
  local_adminpass            = var.win_local_adminpass
  workgroup                  = "local"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}

module "demo_wn1021_clients" {
  source       = "Terraform-VMWare-Modules/vm/vsphere"
  version      = "3.7.0"
  dc           = "Homelab"
  vmrp         = "amd-vmcl02/Resources"
  vmfolder     = "Tanium/Demo"
  datastore    = "vSphere Rust"
  vmtemp       = "Windows Server 2022"
  instances    = 5
  vmname       = "dmo-wndsk"
  vmnameformat = "%01d-2k21"
  ipv4submask  = ["23"]
  network = {
    "VM Network" = ["", "", "", "", ""]
  }
  disk_datastore             = "vSphere Rust"
  dns_server_list            = ["10.0.4.1"]
  vmgateway                  = "10.0.4.1"
  is_windows_image           = true
  local_adminpass            = var.win_local_adminpass
  workgroup                  = "local"
  wait_for_guest_net_timeout = 0
  io_share_level = ["low"]
}
