resource "nsxt_policy_fixed_segment" "active-directory" {
  display_name      = "Homelab - Active Directory"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr        = "172.16.0.1/25"
    dhcp_v4_config {
        dns_servers = [
            "10.0.3.129"
        ]
        lease_time = 86400
    }
  }
}

module "homelab_active-directory" {
  source    = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp    = "Windows Server 2022 Datacenter"
  vmfolder = "Active Directory"
  instances = 3
  cpu_number = 2
  vmname    = "amd-wnad"
  vmrp      = "amd-vmcl02/Resources"
  network = {
    "Homelab - Active Directory" = ["172.16.0.3", "172.16.0.4", "172.16.0.5"]
  }
  vmgateway = "172.16.0.1"
  dc        = "Homelab"
  datastore = "vsanDatastore"
  is_windows_image = true
}

