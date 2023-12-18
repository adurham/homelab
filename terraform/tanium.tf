resource "nsxt_policy_fixed_segment" "tanium" {
  display_name      = "Homelab - Tanium"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.1.1/25"
    dhcp_v4_config {
        dns_servers = [
            "10.0.3.129"
        ]
        lease_time = 86400
    }
  }
}

module "homelab-tanium_server" {
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "TanOS 1.8.1.0165 - Dev"
  vmfolder = "Tanium"
  instances = 2
  cpu_number = 4
  ram_size = 16384
  vmname    = "amd-lxts"
  vmrp      = "amd-vmcl02/Resources"
  domain = "lab.amd-e.com"
  network = {
    "Homelab - Tanium" = ["172.16.1.3", "172.16.1.4"]
  }
  vmgateway = "172.16.1.1"
  dc        = "Homelab"
  datastore = "vsanDatastore"
}

module "homelab-tanium_module_server" {
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "TanOS 1.8.1.0165 - Dev"
  vmfolder = "Tanium"
  instances = 2
  cpu_number = 4
  ram_size = 16384
  vmname    = "amd-lxtms"
  vmrp      = "amd-vmcl02/Resources"
  domain = "lab.amd-e.com"
  network = {
    "Homelab - Tanium" = ["172.16.1.5", "172.16.1.6"]
  }
  vmgateway = "172.16.1.1"
  dc        = "Homelab"
  datastore = "vsanDatastore"
}

module "homelab-tanium_zone_server" {
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "TanOS 1.8.1.0165 - Dev"
  vmfolder = "Tanium"
  instances = 2
  cpu_number = 4
  ram_size = 16384
  vmname    = "amd-lxzs"
  vmrp      = "amd-vmcl02/Resources"
  domain = "lab.amd-e.com"
  network = {
    "Homelab - Tanium" = ["172.16.1.7", "172.16.1.8"]
  }
  vmgateway = "172.16.1.1"
  dc        = "Homelab"
  datastore = "vsanDatastore"
}
