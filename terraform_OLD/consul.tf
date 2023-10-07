# Consul
resource "vsphere_folder" "consul_folder" {
  path          = "${vsphere_folder.vsphere_folder.path}/consul"
  type          = "vm"
  datacenter_id = data.vsphere_datacenter.vsphere_datacenter.id
  tags = [
    "${vsphere_tag.vsphere_terraform_tag.id}",
    "${vsphere_tag.vsphere_environment_tag.id}"
  ]
  depends_on = [
    vsphere_tag.vsphere_terraform_tag,
    vsphere_tag.vsphere_environment_tag,
    vsphere_folder.vsphere_folder,
  ]
}

module "consul_cluster" {
  source          = "Terraform-VMWare-Modules/vm/vsphere"
  version         = "~> 3.5.0"
  dc              = var.vsphere_datacenter
  vmrp            = vsphere_resource_pool.vsphere_homelab_resource_pool.name
  vmfolder        = vsphere_folder.consul_folder.path
  content_library = "Homelab"
  vmtemp          = "Rocky-Server 8.7"
  instances       = var.consul_cluster_instances
  cpu_number      = 2
  firmware        = "efi"
  efi_secure_boot = true
  ram_size        = 4096
  disk_datastore  = var.vsphere_datastore
  disk_size_gb    = ["40"]
  datastore       = var.vsphere_datastore
  data_disk       = {}
  vmname          = "amd-lxcs"
  vmnameformat    = "%02d"
  domain          = var.environment == "production" ? "lab.amd-e.com" : "${var.environment}.lab.amd-e.com"
  ipv4submask     = ["24"]
  network = {
    "${vsphere_distributed_port_group.vsphere_network_port_group.name}" = [for i in range(var.consul_cluster_instances) : ""]
  }

  network_type = ["vmxnet3"]
  tags = {
    "${vsphere_tag_category.vsphere_category.name}" = "${vsphere_tag.vsphere_terraform_tag.name}"
    "${vsphere_tag_category.vsphere_category.name}" = "${vsphere_tag.vsphere_environment_tag.name}"
  }
  depends_on = [
    vsphere_tag.vsphere_terraform_tag,
    vsphere_tag.vsphere_environment_tag,
    vsphere_resource_pool.vsphere_homelab_resource_pool,
    vsphere_folder.consul_folder,
    vsphere_distributed_port_group.vsphere_network_port_group,
  ]
}
