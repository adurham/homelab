packer {
  required_version = "~> 1.8.6"
  required_plugins {
    vsphere = {
      version = "~> v1.1.1"
      source  = "github.com/hashicorp/vsphere"
    }
  }
}

locals {
  buildtime     = formatdate("YYYY-MM-DD hh:mm ZZZ", timestamp())
  manifest_date = formatdate("YYYY-MM-DD hh:mm:ss", timestamp())
  manifest_path = "manifests/"
  data_source_content = {
    "/ks.cfg" = templatefile("http/ks.pkrtpl.hcl", {
      hashed_grub_password   = var.hashed_grub_password
      hashed_admin_password  = var.hashed_admin_password
      hashed_packer_password = var.hashed_packer_password
      ssh_publickey          = var.ssh_publickey
    })
  }
  data_source_command = var.common_data_source == "http" ? "inst.ks=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ks.cfg" : "inst.ks=cdrom:/ks.cfg"
}

source "vsphere-iso" "vsphere" {
  // vSphere settings
  vcenter_server      = var.vsphere_endpoint
  username            = var.vsphere_username
  password            = var.vsphere_password
  insecure_connection = var.vsphere_insecure_connection
  datacenter          = var.vsphere_datacenter
  cluster             = var.vsphere_cluster
  datastore           = var.vsphere_datastore
  folder              = var.vsphere_folder

  // Virtual Machine Settings
  guest_os_type        = var.vm_guest_os_type
  vm_name              = "${var.vm_guest_os_family}-${var.vm_guest_os_vendor}-${var.vm_guest_os_member}-${var.vm_guest_os_version}"
  firmware             = var.vm_firmware
  CPUs                 = var.vm_cpu_sockets
  cpu_cores            = var.vm_cpu_cores
  CPU_hot_plug         = var.vm_cpu_hot_add
  RAM                  = var.vm_mem_size
  RAM_hot_plug         = var.vm_mem_hot_add
  cdrom_type           = var.vm_cdrom_type
  disk_controller_type = var.vm_disk_controller_type
  storage {
    disk_size             = var.vm_disk_size
    disk_thin_provisioned = var.vm_disk_thin_provisioned
  }
  network_adapters {
    network      = var.vsphere_network
    network_card = var.vm_network_card
  }
  vm_version           = var.common_vm_version
  remove_cdrom         = var.common_remove_cdrom
  tools_upgrade_policy = var.common_tools_upgrade_policy
  notes                = "Built by HashiCorp Packer on ${local.buildtime}."

  // Removable Media Settings
  iso_paths    = ["${var.common_iso_datastore}/${var.iso_path}/${var.iso_file}"]
  iso_checksum = "${var.iso_checksum_type}:${var.iso_checksum_value}"
  http_content = var.common_data_source == "http" ? local.data_source_content : null
  cd_content   = var.common_data_source == "disk" ? local.data_source_content : null

  // Boot and Provisioning Settings
  http_ip       = var.common_data_source == "http" ? var.common_http_ip : null
  http_port_min = var.common_data_source == "http" ? var.common_http_port_min : null
  http_port_max = var.common_data_source == "http" ? var.common_http_port_max : null
  boot_order    = var.vm_boot_order
  boot_wait     = var.vm_boot_wait
  boot_command = [
    "up",
    "e",
    "<down><down><end><wait>",
    "text ${local.data_source_command}",
    "<enter><wait><leftCtrlOn>x<leftCtrlOff>"
  ]
  ip_wait_timeout  = var.common_ip_wait_timeout
  shutdown_timeout = var.common_shutdown_timeout

  // Communicator Settings and Credentials
  communicator = "ssh"
  ssh_username = var.build_username
  ssh_password = var.build_password
  ssh_port     = var.communicator_port
  ssh_timeout  = var.communicator_timeout

  // Template and Content Library Settings
  convert_to_template = var.common_template_conversion
  content_library_destination {
    library     = var.common_content_library_name
    name        = "${title(var.vm_guest_os_vendor)}-${title(var.vm_guest_os_member)} ${var.vm_guest_os_version}"
    description = "${title(var.vm_guest_os_vendor)}-${title(var.vm_guest_os_member)} ${var.vm_guest_os_version}: With DISA STIG applied."
    destroy     = var.common_content_library_destroy
    ovf         = var.common_content_library_ovf
    skip_import = var.common_content_library_skip_import
  }
}

build {
  sources = ["source.vsphere-iso.vsphere"]
  provisioner "shell" {
    remote_file     = "script.sh"
    execute_command = "sudo mv {{ .Path }} /run/; chmod +x /run/script.sh; sudo env {{ .Vars }} /run/script.sh"
    environment_vars = [
    ]
    scripts = ["scripts/base.sh"]
  }
  post-processor "manifest" {
    output     = "${local.manifest_path}${local.manifest_date}.json"
    strip_path = true
    strip_time = true
    custom_data = {
      build_username           = var.build_username
      buildtime                = local.buildtime
      common_data_source       = var.common_data_source
      common_vm_version        = var.common_vm_version
      vm_cpu_cores             = var.vm_cpu_cores
      vm_cpu_sockets           = var.vm_cpu_sockets
      vm_disk_size             = var.vm_disk_size
      vm_disk_thin_provisioned = var.vm_disk_thin_provisioned
      vm_firmware              = var.vm_firmware
      vm_guest_os_type         = var.vm_guest_os_type
      vm_mem_size              = var.vm_mem_size
      vm_network_card          = var.vm_network_card
      vsphere_cluster          = var.vsphere_cluster
      vsphere_datacenter       = var.vsphere_datacenter
      vsphere_datastore        = var.vsphere_datastore
      vsphere_endpoint         = var.vsphere_endpoint
      vsphere_folder           = var.vsphere_folder
      vsphere_iso_path         = "${var.common_iso_datastore}/${var.iso_path}/${var.iso_file}"
    }
  }
}