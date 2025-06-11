locals {
  #--------------------------------------------------------------------
  # Common Infrastructure Settings
  #--------------------------------------------------------------------
  dns_servers = ["10.0.3.129"]
  lease_time  = 86400

  #--------------------------------------------------------------------
  # vSphere Host & Cluster Definitions
  #--------------------------------------------------------------------
  esxi_hosts = {
    "amd-hwvm05" = {
      hostname = "amd-hwvm05.lab.amd-e.com"
      ip       = "10.0.1.76"
      vmnics_1g  = ["vmnic0", "vmnic1"]
      vmnics_10g = ["vmnic2", "vmnic3"]
    },
    "amd-hwvm06" = {
      hostname = "amd-hwvm06.lab.amd-e.com"
      ip       = "10.0.1.77"
      vmnics_1g  = ["vmnic0", "vmnic1"]
      vmnics_10g = ["vmnic2", "vmnic3"]
    },
    "amd-hwvm07" = {
      hostname = "amd-hwvm07.lab.amd-e.com"
      ip       = "10.0.1.78"
      vmnics_1g  = ["vmnic0", "vmnic1"]
      vmnics_10g = ["vmnic2", "vmnic3"]
    },
    "amd-hwvm08" = {
      hostname = "amd-hwvm08.lab.amd-e.com"
      ip       = "10.0.1.79"
      vmnics_1g  = ["vmnic0", "vmnic1"]
      vmnics_10g = ["vmnic2", "vmnic3"]
    }
  }

  cl02_vsan_disk_groups = [
    {
      cache = "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S4X4NE0M807776P_____"
      storage = ["t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S3Z6NBRK604342T_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S4X4NE0M807763P_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N908125N_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N908147M_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N910934E_____"]
    },
    {
      cache = "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N910949D_____"
      storage = ["t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S4X4NE0M807767D_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S4X4NE0M809030W_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N910931A_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N910948L_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S5JANJ0N204384Y_____"]
    },
    {
      cache = "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S3Z6NB0M502083T_____"
      storage = ["t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S3Z6NB0K320703N_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S3Z6NB0M500722F_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S599NE0MA14277Z_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S5J0NR0NB06456J_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S5JANE0MB04849D_____"]
    },
    {
      cache = "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S599NJ0N111666A_____"
      storage = ["t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S3Z6NW0K714529E_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S599NZ0NB00939F_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N909799N_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S59VNS0N910950P_____", "t10.ATA_____Samsung_SSD_860_EVO_1TB_________________S5B3NR0NB11832Y_____"]
    }
  ]

  # Clusters & Datastores
  datastore_flash    = "vSphere Flash"
  datastore_rust     = "vSphere Rust"
  datastore_vsan     = "vsanDatastore"
  cl02_resource_pool = "${vsphere_compute_cluster.cl02.name}/Resources"

  #--------------------------------------------------------------------
  # Service & VM Definitions
  #--------------------------------------------------------------------
  ws22dc_template = "Windows Server 2022 Datacenter"

  low_resource_vm_specs = {
    cpu_number      = 2
    ram_size        = 4096
    cpu_share_level = "low"
    io_share_level  = ["low"]
  }

  # Define the unique inputs for each application/service
  service_definitions = {
    active_directory = {
      cidr = "172.16.0.1/25"
      # Combined Federation Services and Certificate Authority IPs with original AD IPs
      ips = ["172.16.0.3", "172.16.0.4", "172.16.0.5", "172.16.0.6", "172.16.0.7", "172.16.0.8", "172.16.0.9", "172.16.0.10", "172.16.0.11"]
    },
    consul = {
      cidr = "172.16.0.129/28"
      ips  = ["172.16.0.131", "172.16.0.132", "172.16.0.133"]
    },
    vault = {
      cidr = "172.16.0.145/28"
      ips  = ["172.16.0.146", "172.16.0.147", "172.16.0.148"]
    },
    keycloak = {
      cidr = "172.16.0.161/28"
      ips  = ["172.16.0.162"]
    }
  }

  # Use a for-loop to generate a consistent data structure for all services
  # This replaces all the old repetitive blocks for AD, Consul, Vault, etc.
  services = {
    for name, config in local.service_definitions : name => {
      cidr         = config.cidr
      gateway      = cidrhost(config.cidr, 1)
      netmask      = cidrnetmask(config.cidr)
      netmask_cidr = tonumber(regex("^[0-9\\.]+/(\\d+)$", config.cidr)[0])
      ips          = config.ips
      vm_specs = {
        cpu_number      = 2
        ram_size        = 4096
        cpu_share_level = "normal"
        io_share_level  = ["normal"]
      }
    }
  }
}