terraform {
  required_providers {
    vsphere = {
      source  = "hashicorp/vsphere"
      version = "~> 2.4.2"
    }
    http = {
      source = "hashicorp/http"
      version = "~> 3.4.0"
    }
    null = {
      source = "hashicorp/null"
      version = "~> 3.2.1"
    }
  }
}

provider "vsphere" {
  vsphere_server       = var.vsphere_endpoint
  user                 = var.vsphere_username
  password             = var.vsphere_password
  allow_unverified_ssl = var.vsphere_insecure_connection
}

provider "http" {
  alias = "opnsense"
}

provider "null" {
  
}