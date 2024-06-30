resource "nsxt_policy_fixed_segment" "vault" {
  display_name      = "Vault"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr = "172.16.0.145/28"
    dhcp_v4_config {
      dns_servers = var.dns_servers
      lease_time  = var.lease_time
    }
  }
}

resource "vsphere_folder" "vault" {
  path          = "Vault"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-vault_server" {
  depends_on = [
    nsxt_policy_fixed_segment.vault,
    vsphere_folder.vault
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.vault.path
  instances  = 3
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-lxvlt"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.vault.display_name}" = ["172.16.0.195", "172.16.0.196", "172.16.0.197"]
  }
  vmgateway       = "172.16.0.193"
  dns_server_list = [nsxt_policy_fixed_segment.vault.subnet[0].dhcp_v4_config[0].dns_servers[0]]
  dc              = vsphere_datacenter.Homelab.name
  datastore       = "vsanDatastore"
}
