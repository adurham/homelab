variable "esxi_password" {
  type        = string
  description = "The password for the ESXi server"
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
variable "vcenter_endpoint" {
  type        = string
  description = "The FQDN of the vCenter server"
}
variable "vcenter_license" {
  type        = string
  description = "The license for the vCenter server"
  sensitive   = true
}
variable "vcenter_username" {
  type        = string
  description = "The username for the vCenter server"
  sensitive   = true
}
variable "vcenter_password" {
  type        = string
  description = "The password for the vCenter server"
  sensitive   = true
}
variable "vcenter_insecure_connection" {
  type        = bool
  description = "Don't validate vCenter Server TLS certificate"
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
variable "nsx_transport_node_cli_username" {
  type        = string
  description = "The CLI username for the NSX Transport server"
  sensitive   = true
}
variable "nsx_transport_node_cli_password" {
  type        = string
  description = "The CLI password for the NSX Transport server"
  sensitive   = true
}
variable "nsx_transport_node_root_password" {
  type        = string
  description = "The root password for the NSX Transport server"
  sensitive   = true
}
variable "win_local_adminpass" {
  type        = string
  description = "The password for the Windows local admin account"
  sensitive   = true
}
variable "domain" {
  type        = string
  description = "FQDN to use in multiple places"
}
variable "domainuser" {
  type        = string
  description = "The user for the Windows domain join"
  sensitive   = true
}
variable "domainpass" {
  type        = string
  description = "The password for the Windows domain join"
  sensitive   = true
}
