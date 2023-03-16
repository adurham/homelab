data "vsphere_datacenter" "vsphere_datacenter" {
  name = var.vsphere_datacenter
}

data "vsphere_compute_cluster" "vsphere_compute_cluster" {
  name          = var.vsphere_compute_cluster
  datacenter_id = data.vsphere_datacenter.vsphere_datacenter.id
}

resource "vsphere_tag_category" "vsphere_category" {
  name        = "${var.environment}-category"
  cardinality = "MULTIPLE"
  description = "Managed by Terraform"
  associable_types = [
    "Folder",
    "DistributedVirtualPortgroup",
    "ResourcePool",
    "VirtualMachine",
  ]
}

resource "vsphere_tag" "vsphere_terraform_tag" {
  name        = "terraform"
  category_id = vsphere_tag_category.vsphere_category.id
  description = "Managed by Terraform"
  depends_on = [
    vsphere_tag_category.vsphere_category,
  ]
}

resource "vsphere_tag" "vsphere_environment_tag" {
  name        = var.environment
  category_id = vsphere_tag_category.vsphere_category.id
  description = "Terraform environment"
  depends_on = [
    vsphere_tag_category.vsphere_category,
  ]
}

resource "vsphere_resource_pool" "vsphere_homelab_resource_pool" {
  name                    = "${var.environment} Resource Pool"
  parent_resource_pool_id = data.vsphere_compute_cluster.vsphere_compute_cluster.resource_pool_id
  cpu_share_level         = "normal"
  # cpu_shares               = 4000
  cpu_reservation    = 0
  cpu_expandable     = true
  cpu_limit          = -1
  memory_share_level = "normal"
  # memory_shares            = 2048
  memory_reservation       = 0
  memory_expandable        = true
  memory_limit             = -1
  scale_descendants_shares = "disabled"
  tags = [
    "${vsphere_tag.vsphere_terraform_tag.id}",
    "${vsphere_tag.vsphere_environment_tag.id}"
  ]
  depends_on = [
    vsphere_tag.vsphere_terraform_tag,
    vsphere_tag.vsphere_environment_tag
  ]
}

resource "vsphere_folder" "vsphere_folder" {
  path          = var.environment
  type          = "vm"
  datacenter_id = data.vsphere_datacenter.vsphere_datacenter.id
  tags = [
    "${vsphere_tag.vsphere_terraform_tag.id}",
    "${vsphere_tag.vsphere_environment_tag.id}"
  ]
  depends_on = [
    vsphere_tag.vsphere_terraform_tag,
    vsphere_tag.vsphere_environment_tag
  ]
}

resource "vsphere_distributed_port_group" "vsphere_network_port_group" {
  name                            = var.environment
  distributed_virtual_switch_uuid = "50 12 25 e8 1c 25 5a d7-02 d1 d5 92 65 91 19 5e"
  vlan_id                         = var.vlan_tag
  tags = [
    "${vsphere_tag.vsphere_terraform_tag.id}",
    "${vsphere_tag.vsphere_environment_tag.id}"
  ]
  depends_on = [
    vsphere_tag.vsphere_terraform_tag,
    vsphere_tag.vsphere_environment_tag
  ]
}
