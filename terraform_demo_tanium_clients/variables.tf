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
  description = "Don't validate vSphere Server TLS certificate"
  default     = false
}
variable "win_local_adminpass" {
  type        = string
  description = "The password for the Windows local admin account"
  sensitive   = true
}