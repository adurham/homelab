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
variable "vsphere_datacenter" {
  type        = string
  description = "The name of the target vSphere datacenter"
}
variable "vsphere_compute_cluster" {
  type = string
  description = "The name of the target vSphere compute cluster"
}
variable "environment" {
  type = string
  description = "The name of the target environment"
}
variable "vlan_tag" {
  type = number
  description = "The id of the target vlan tag"
}