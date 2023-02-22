variable "headless" {
  type    = string
  default = "true"
}

variable "shutdown_command" {
  type    = string
  default = "sudo /sbin/halt -p"
}

variable "version" {
  type    = string
  default = "8.7"
}

variable "vcenter_username" {
  type        = string
  description = "The username for the vcenter server"
  sensitive   = true
}

variable "vcenter_password" {
  type        = string
  description = "The password for the vcenter server"
  sensitive   = true
}

variable "ssh_username" {
  type        = string
  description = "The username for the SSH user"
  sensitive   = true
}

variable "ssh_password" {
  type        = string
  description = "The password for the SSH user"
  sensitive   = true
}

source "vsphere-iso" "vsphere" {
  vcenter_server                 = "10.0.4.2"
  insecure_connection            = "false"
  username                       = "${var.vcenter_username}"
  password                       = "${var.vcenter_password}"
  datacenter                     = "Homelab"

  vm_name                        = "Rocky Linux 8.7 Base"
  folder                         = "Templates/Temp"
  cluster                        = "amd-vmcl2"
  datastore                      = "vSphere"

  CPUs                           = "2"
  RAM                            = "4096"
  firmware                       = "efi-secure"
  disk_controller_type           = ["pvscsi"]
  storage {
    disk_size                    = "40960"
    disk_thin_provisioned        = "true"
  }

  guest_os_type                  = "rhel8_64Guest"
  iso_paths = ["Homelab/Rocky Linux 8.7 ISO/Rocky-8.7-x86_64-dvd1.iso"]

  boot_command = [
    "<esc>c",
    "linuxefi /images/pxeboot/vmlinuz inst.stage2=hd:LABEL=Rocky-8-7-x86_64-dvd inst.ks=cdrom:/ks.cfg rd.live.check<enter>",
    "initrdefi /images/pxeboot/initrd.img<enter>",
    "boot<enter><wait>"
  ]

  cd_files                       = ["http/ks.cfg"]
  cd_label                       = "kickstart"

  network_adapters {
    network                      = "amd-vmcl2 VM Network"
    network_card                 = "vmxnet3"
  }

  shutdown_command               = "${var.shutdown_command}"
  ssh_username                   = "${var.ssh_username}"
  ssh_password                   = "${var.ssh_password}"
  ssh_timeout                    = "20m"
}

build {
  sources = ["source.vsphere-iso.vsphere"]

  provisioner "shell" {
    environment_vars = [
      "SUDO_PASS=${var.ssh_password}"
    ]
    scripts         = ["scripts/base.sh"]
  }
}