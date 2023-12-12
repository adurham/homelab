variable "esxi_password" {
  type        = string
  description = "The password for the vSphere server"
  sensitive   = true
}
variable "esxi_7_license" {
  type        = string
  description = "The license for ESXi 7"
  sensitive   = true
}
variable "esxi_8_license" {
  type        = string
  description = "The license for ESXi 8"
  sensitive   = true
}
variable "vsphere_endpoint" {
  type        = string
  description = "The FQDN of the vSphere server"
}
variable "vcenter_license" {
  type        = string
  description = "The license for the vSphere server"
  sensitive   = true
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
  description = "Don't validate vSphere Server TLS certificate"
  default     = false
}
variable "nsx_endpoint" {
  type        = string
  description = "The FQDN of the NSX server"
}
variable "nsx_username" {
  type        = string
  description = "The username for the NSX server"
  sensitive   = true
}
variable "nsx_password" {
  type        = string
  description = "The password for the NSX server"
  sensitive   = true
}
variable "nsx_insecure_connection" {
  type        = bool
  description = "Don't validate NSX Server TLS certificate"
  default     = false
}
variable "win_local_adminpass" {
  type        = string
  description = "The password for the Windows local admin account"
  sensitive   = true
}
