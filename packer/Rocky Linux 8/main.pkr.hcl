locals {
  data_source_content = {
    "ks.cfg" = templatefile("http/ks.pkrtpl.hcl", {
      hashed_grub_password   = var.hashed_grub_password
      hashed_admin_password  = var.hashed_admin_password
      hashed_packer_password = var.hashed_packer_password
      ssh_publickey          = var.ssh_publickey
    })
  }
}


source "vsphere-iso" "vsphere" {
  vcenter_server       = "10.0.4.2"
  insecure_connection  = "false"
  username             = "${var.vcenter_username}"
  password             = "${var.vcenter_password}"
  datacenter           = "Homelab"
  vm_name              = "Rocky Linux 8.7 Base-temp"
  folder               = "Templates/Temp"
  cluster              = "amd-vmcl2"
  datastore            = "vSphere"
  CPUs                 = "2"
  RAM                  = "4096"
  firmware             = "efi-secure"
  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = "40960"
    disk_thin_provisioned = "true"
  }
  guest_os_type = "rhel8_64Guest"
  iso_paths     = ["Homelab/Rocky Linux 8.7 ISO/Rocky-8.7-x86_64-dvd1.iso"]
  boot_command = [
    "<esc>c",
    "linuxefi /images/pxeboot/vmlinuz inst.stage2=hd:LABEL=Rocky-8-7-x86_64-dvd inst.ks=cdrom:/ks.cfg<enter>",
    "initrdefi /images/pxeboot/initrd.img<enter>",
    "boot<enter><wait>"
  ]
  // cd_files     = ["http/ks.cfg"]
  cd_content   = local.data_source_content
  cd_label     = "kickstart"
  cdrom_type   = "sata"
  remove_cdrom = true
  network_adapters {
    network      = "amd-vmcl2 VM Network"
    network_card = "vmxnet3"
  }
  ssh_username = "${var.ssh_username}"
  // ssh_password = "${var.ssh_password}"
  // ssh_private_key_file = "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
  ssh_timeout = "20m"
  content_library_destination {
    library     = "Homelab"
    name        = "Rocky Linux 8.7 Base"
    description = "Rocky Linux 8 base OS image with DISA STIG applied."
    folder      = "Templates"
    ovf         = true
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
}