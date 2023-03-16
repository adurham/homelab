// vSphere settings
vsphere_endpoint = "amd-vmvc01.lab.amd-e.com"
vsphere_insecure_connection = false
vsphere_datacenter = "Homelab"
vsphere_cluster = "amd-vmcl2"
vsphere_datastore = "vSphere"
vsphere_network = "amd-vmcl2 VM Network"
vsphere_folder = "Templates/Temp"

// Common Settings
common_vm_version = 19
common_remove_cdrom = true
common_tools_upgrade_policy = false
common_iso_datastore = "Homelab"
common_data_source = "disk"
common_http_ip = null
common_http_port_min = null
common_http_port_max = null
common_ip_wait_timeout = "30m"
common_shutdown_timeout = "5m"
common_template_conversion = false
common_content_library_name = "Homelab"
common_content_library_ovf = true
common_content_library_destroy = true
common_content_library_skip_import = false

// Guest Operating System Metadata
vm_guest_os_language = "en_US"
vm_guest_os_keyboard = "us"
vm_guest_os_timezone = "UTC"
vm_guest_os_family   = "linux"
vm_guest_os_vendor   = "rocky"
vm_guest_os_member   = "server"
vm_guest_os_version  = "8.7"
vm_guest_os_type = "rhel8_64Guest"

// Virtual Machine Hardware Settings
vm_firmware              = "efi-secure"
vm_cdrom_type            = "sata"
vm_cpu_sockets           = 2
vm_cpu_cores             = 1
vm_cpu_hot_add           = false
vm_mem_size              = 4096
vm_mem_hot_add           = false
vm_disk_size             = 40960
vm_disk_controller_type  = ["pvscsi"]
vm_disk_thin_provisioned = true
vm_network_card          = "vmxnet3"

// Removable Media Settings
iso_path           = "Rocky Linux 8.7 ISO"
iso_file           = "Rocky-8.7-x86_64-dvd1.iso"
iso_checksum_type  = "sha256"
iso_checksum_value = "4827dce1c58560d3ca470a5053e8d86ba059cbb77cfca3b5f6a5863d2aac5b84"

// Boot Settings
vm_boot_order = "disk,cdrom"
vm_boot_wait  = "2s"

// Communicator Settings
communicator_port    = 22
communicator_timeout = "30m"

// Provisioner Settings
scripts = ["scripts/base.sh"]
inline  = []
