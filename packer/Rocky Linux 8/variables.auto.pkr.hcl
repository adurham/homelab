// vSphere settings
variable "vsphere_endpoint" {
  type        = string
  description = "The FQDN of the vSphere server"
}
variable "vsphere_username" {
  type        = string
  description = "The username for the vSphere server"
  sensitive   = true
}
variable "vsphere_password" {
  type        = string
  description = "The password for the vSphere server"
  sensitive   = true
}
variable "vsphere_insecure_connection" {
  type        = bool
  description = "Do not validate vSphere Server TLS certificate."
  default     = false
}
variable "vsphere_datacenter" {
  type        = string
  description = "The name of the target vSphere datacenter"
}
variable "vsphere_cluster" {
  type        = string
  description = "The name of the target vSphere cluster"
}
variable "vsphere_datastore" {
  type        = string
  description = "The name of the target vSphere datastore"
}
variable "vsphere_network" {
  type        = string
  description = "The name of the target vSphere network"
}
variable "vsphere_folder" {
  type        = string
  description = "The name of the target vSphere folder"
}

// VM Settings
variable "vm_guest_os_language" {
  type        = string
  description = "The guest operating system lanugage"
  default     = "en_US"
}
variable "vm_guest_os_keyboard" {
  type        = string
  description = "The guest operating system keyboard input"
  default     = "us"
}
variable "vm_guest_os_timezone" {
  type        = string
  description = "The guest operating system timezone"
  default     = "UTC"
}
variable "vm_guest_os_family" {
  type        = string
  description = "The guest operating system family"
}
variable "vm_guest_os_vendor" {
  type        = string
  description = "The guest operating system vendor"
}
variable "vm_guest_os_member" {
  type        = string
  description = "The guest operating system member"
}
variable "vm_guest_os_version" {
  type        = string
  description = "The guest operating system version"
}
variable "vm_guest_os_type" {
  type        = string
  description = "The guest operating system type"
}
variable "vm_firmware" {
  type        = string
  description = "The virtual machine firmware"
  default     = "efi-secure"
}
variable "vm_cdrom_type" {
  type        = string
  description = "The virtual machine CD-ROM type"
  default     = "sata"
}
variable "vm_cpu_sockets" {
  type        = number
  description = "The number of virtual CPUs sockets"
  default     = 1
}
variable "vm_cpu_cores" {
  type        = number
  description = "The number of virtual CPUs cores per socket"
  default     = 1
}
variable "vm_cpu_hot_add" {
  type        = bool
  description = "Enable hot add CPU."
  default     = false
}
variable "vm_mem_size" {
  type        = number
  description = "The size for the virtual memory in MB"
  default     = 1024
}
variable "vm_mem_hot_add" {
  type        = bool
  description = "Enable hot add memory."
  default     = false
}
variable "vm_disk_size" {
  type        = number
  description = "The size for the virtual disk in MB"
  default     = 1024
}
variable "vm_disk_controller_type" {
  type        = list(string)
  description = "The virtual disk controller types in sequence"
  default     = ["pvscsi"]
}
variable "vm_disk_thin_provisioned" {
  type        = bool
  description = "Thin provision the virtual disk."
  default     = true
}
variable "vm_network_card" {
  type        = string
  description = "The virtual network card type"
  default     = "vmxnet3"
}
variable "common_vm_version" {
  type        = number
  description = "The vSphere virtual hardware version"
}
variable "common_tools_upgrade_policy" {
  type        = bool
  description = "Upgrade VMware Tools on reboot"
  default     = true
}
variable "common_remove_cdrom" {
  type        = bool
  description = "Remove the virtual CD-ROM(s)"
  default     = true
}

// Template and Content Library Settings
variable "common_template_conversion" {
  type        = bool
  description = "Convert the virtual machine to template. Must be 'false' for content library"
  default     = false
}
variable "common_content_library_name" {
  type        = string
  description = "The name of the target vSphere content library"
  default     = null
}
variable "common_content_library_ovf" {
  type        = bool
  description = "Export to content library as an OVF template"
  default     = true
}
variable "common_content_library_destroy" {
  type        = bool
  description = "Delete the virtual machine after exporting to the content library"
  default     = true
}
variable "common_content_library_skip_import" {
  type        = bool
  description = "Skip exporting the virtual machine to the content library"
  default     = false
}

// Removable Media Settings
variable "common_iso_datastore" {
  type        = string
  description = "The name of the source vSphere datastore for ISO images"
}
variable "iso_path" {
  type        = string
  description = "The path on the source vSphere datastore for ISO image"
}
variable "iso_file" {
  type        = string
  description = "The file name of the ISO image used by the vendor"
}
variable "iso_checksum_type" {
  type        = string
  description = "The checksum algorithm used by the vendor"
}
variable "iso_checksum_value" {
  type        = string
  description = "The checksum value provided by the vendor"
}

// Boot Settings
variable "common_data_source" {
  type        = string
  description = "The provisioning data source ('http' or 'disk')"
}
variable "common_http_ip" {
  type        = string
  description = "Define an IP address on the host to use for the HTTP server"
  default     = null
}
variable "common_http_port_min" {
  type        = number
  description = "The start of the HTTP port range"
}
variable "common_http_port_max" {
  type        = number
  description = "The end of the HTTP port range"
}
variable "vm_boot_order" {
  type        = string
  description = "The boot order for virtual machines devices"
  default     = "disk,cdrom"
}
variable "vm_boot_wait" {
  type        = string
  description = "The time to wait before boot"
}
variable "common_ip_wait_timeout" {
  type        = string
  description = "Time to wait for guest operating system IP address response"
}
variable "common_shutdown_timeout" {
  type        = string
  description = "Time to wait for guest operating system shutdown"
}

// Communicator Settings and Credentials
variable "build_username" {
  type        = string
  description = "The username to login to the guest operating system"
  sensitive   = true
  default     = null
}
variable "build_password" {
  type        = string
  description = "The password to login to the guest operating system"
  sensitive   = true
  default     = null
}
variable "build_password_encrypted" {
  type        = string
  description = "The encrypted password to login the guest operating system"
  sensitive   = true
  default     = null
}
variable "communicator_port" {
  type        = string
  description = "The port for the communicator protocol."
}
variable "communicator_timeout" {
  type        = string
  description = "The timeout for the communicator protocol."
}

// Provisioner Settings
variable "scripts" {
  type        = list(string)
  description = "A list of scripts and their relative paths to transfer and execute"
  default     = []
}
variable "inline" {
  type        = list(string)
  description = "A list of commands to execute"
  default     = []
}

// VM Specific variables
variable "ssh_publickey" {
  type        = string
  description = "The publickey for the SSH user"
  sensitive   = true
}
variable "hashed_admin_password" {
  type        = string
  description = "SHA512 of the password for the Admin user"
  sensitive   = true
}
variable "hashed_packer_password" {
  type        = string
  description = "SHA512 of the password for the Packer user"
  sensitive   = true
}
variable "hashed_grub_password" {
  type        = string
  description = "SHA512 of the grub bootloader password"
  sensitive   = true
}