provider "vsphere" {
  vsphere_server       = var.vsphere_endpoint
  user                 = var.vsphere_username
  password             = var.vsphere_password
  allow_unverified_ssl = var.vsphere_insecure_connection
}
