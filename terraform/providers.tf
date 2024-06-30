terraform {
  required_providers {
    vsphere = {
      source  = "hashicorp/vsphere"
      version = "~> 2.8.1"
    }
    nsxt = {
      source  = "vmware/nsxt"
      version = "~> 3.4.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.2"
    }
  }
}

provider "vsphere" {
  vsphere_server       = var.vcenter_endpoint
  user                 = var.vcenter_username
  password             = var.vcenter_password
  allow_unverified_ssl = var.vcenter_insecure_connection
}

provider "nsxt" {
  host                 = var.nsx_endpoint
  username             = var.nsx_username
  password             = var.nsx_password
  allow_unverified_ssl = var.nsx_insecure_connection
  max_retries          = 2
}

provider "null" {

}
