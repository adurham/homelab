resource "vsphere_folder" "tanium_clients" {
  path          = "${vsphere_folder.tanium.path}/Clients"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}

resource "vsphere_folder" "tanium_qa_clients" {
  path          = "${vsphere_folder.tanium_clients.path}/QA Clients"
  type          = "vm"
  datacenter_id = vsphere_datacenter.Homelab.moid
}
