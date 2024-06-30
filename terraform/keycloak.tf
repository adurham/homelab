resource "nsxt_policy_fixed_segment" "keycloak" {
  display_name      = "Keycloak"
  description       = "Terraform provisioned Segment"
  connectivity_path = nsxt_policy_tier1_gateway.tier1_gw.path
  subnet {
    cidr = "172.16.0.161/28"
    dhcp_v4_config {
      dns_servers = var.dns_servers
      lease_time  = var.lease_time
    }
  }
}

resource "vsphere_folder" "keycloak" {
  path          = "Keycloak"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-keycloak_server" {
  depends_on = [
    nsxt_policy_fixed_segment.keycloak,
    vsphere_folder.keycloak
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.keycloak.path
  instances  = 1
  cpu_number = 2
  ram_size   = 4096
  vmname     = "amd-lxkycl"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.keycloak.display_name}" = ["172.16.0.162"]
  }
  ipv4submask     = ["28"]
  vmgateway       = "172.16.0.161"
  dns_server_list = [nsxt_policy_fixed_segment.keycloak.subnet[0].dhcp_v4_config[0].dns_servers[0]]
  dc              = vsphere_datacenter.Homelab.name
  datastore       = "vsanDatastore"
}
