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
variable "vsphere_datastore" {
  type = string
  description = "The name of the target vSphere datastore cluster"
}
variable "environment" {
  type = string
  description = "The name of the target environment"
}
variable "vlan_tag" {
  type = number
  description = "The id of the target vlan tag"
}
variable "vsphere_module_version" {
  type = string
  description = "The version of the vSphere VM module to use"
}
variable "consul_cluster_instances" {
  type = number
  description = "The number of VMs to spin up for Consul"
}
variable "opnsense_endpoint" {
  type        = string
  description = "The FQDN of the opnsense server"
}
variable "opnsense_username" {
  type        = string
  description = "The username for the opnsense server"
  sensitive   = true
}
variable "opnsense_password" {
  type        = string
  description = "The password for the opnsense server"
  sensitive   = true
}