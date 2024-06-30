resource "nsxt_policy_fixed_segment" "consul" {
  display_name      = "Consul"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr = "172.16.0.129/28"
    dhcp_v4_config {
      dns_servers = [
        "10.0.3.129"
      ]
      lease_time = 86400
    }
  }
}

resource "vsphere_folder" "consul" {
  path          = "Consul"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-consul_server" {
  depends_on = [
    nsxt_policy_fixed_segment.consul,
    vsphere_folder.consul
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.consul.path
  instances  = 3
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-lxcnsl"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.consul.display_name}" = ["172.16.0.131", "172.16.0.132", "172.16.0.133"]
  }
  vmgateway       = "172.16.0.129"
  dns_server_list = [nsxt_policy_fixed_segment.consul.subnet[0].dhcp_v4_config[0].dns_servers[0]]
  dc              = vsphere_datacenter.Homelab.name
  datastore       = "vsanDatastore"
}
