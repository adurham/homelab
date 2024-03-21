resource "vsphere_folder" "tanium_grafana" {
  path          = "${vsphere_folder.tanium.path}/Grafana"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

module "homelab-tanium_grafana" {
  depends_on = [
    nsxt_policy_fixed_segment.tanium,
    vsphere_folder.tanium_grafana
  ]
  source     = "git@github.com:adurham/terraform-vsphere-vm.git?ref=v3.8.1"
  vmtemp     = "Ubuntu Linux 22.04"
  vmfolder   = vsphere_folder.tanium_grafana.path
  instances  = 1
  cpu_number = 6
  ram_size   = 65536
  vmname     = "amd-tngf"
  vmrp       = "${vsphere_compute_cluster.cl02.name}/Resources"
  domain     = "lab.amd-e.com"
  network = {
    "${nsxt_policy_fixed_segment.tanium.display_name}" = ["172.16.1.13"]
  }
  vmgateway = "172.16.1.1"
  dns_server_list = ["10.0.3.129"]
  dc        = vsphere_datacenter.Homelab.name
  datastore = "vsanDatastore"
}