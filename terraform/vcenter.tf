resource "vsphere_license" "licenseKey" {
  license_key = var.vcenter_license
}

resource "vsphere_datacenter" "Homelab" {
  name = "Homelab"
}

#--------------------------------------------------------------------
# ESXi Hosts for amd-vmcl02 Cluster
#--------------------------------------------------------------------

# Create all thumbprints with a single block
data "vsphere_host_thumbprint" "host_thumbprints" {
  for_each = local.esxi_hosts
  address  = each.value.ip
  insecure = true
}

# Create all 4 hosts with a single resource block
resource "vsphere_host" "hosts" {
  for_each   = local.esxi_hosts
  hostname   = each.value.hostname
  thumbprint = data.vsphere_host_thumbprint.host_thumbprints[each.key].id
  username   = "root"
  password   = var.esxi_password
  license    = var.esxi_8_license
  lockdown   = "disabled"
  services {
    ntpd {
      enabled     = true
      ntp_servers = ["10.0.1.65"]
      policy      = "on"
    }
  }
  lifecycle {
    ignore_changes = [
      cluster,
    ]
  }
}

#--------------------------------------------------------------------
# Compute Cluster and Networking
#--------------------------------------------------------------------

resource "vsphere_compute_cluster" "cl02" {
  name          = "amd-vmcl02"
  datacenter_id = vsphere_datacenter.Homelab.moid
  host_system_ids = [for host in vsphere_host.hosts : host.id]

  # DRS Settings
  drs_enabled                  = true
  drs_automation_level         = "fullyAutomated"
  drs_migration_threshold      = 3
  drs_scale_descendants_shares = "disabled"
  
  # HA Settings
  ha_enabled                   = true
  ha_datastore_apd_response    = "restartConservative"
  ha_datastore_pdl_response    = "restartAggressive"
  ha_heartbeat_datastore_policy = "allFeasibleDsWithUserPreference"
  
  # DPM Settings
  dpm_enabled                  = false
  dpm_automation_level         = "automated"

  # vSAN Settings
  vsan_enabled                 = true
  vsan_compression_enabled     = true
  vsan_dedup_enabled           = true
  vsan_performance_enabled     = true
  vsan_unmap_enabled           = true

  # This dynamic block now uses the namespaced local variable
  dynamic "vsan_disk_group" {
    for_each = local.cl02_vsan_disk_groups
    content {
      cache   = vsan_disk_group.value.cache
      storage = vsan_disk_group.value.storage
    }
  }
}

resource "vsphere_distributed_virtual_switch" "vds01" {
  name          = "1GbE0"
  datacenter_id = vsphere_datacenter.Homelab.moid

  dynamic "host" {
    for_each = vsphere_host.hosts
    content {
      host_system_id = host.value.id
      devices        = local.esxi_hosts[host.key].vmnics_1g
    }
  }
}

resource "vsphere_distributed_virtual_switch" "vds02" {
  name          = "10GbE0"
  datacenter_id = vsphere_datacenter.Homelab.moid

  dynamic "host" {
    for_each = vsphere_host.hosts
    content {
      host_system_id = host.value.id
      devices        = local.esxi_hosts[host.key].vmnics_10g
    }
  }
}

resource "vsphere_distributed_port_group" "vds01_vdpg01" {
  name                            = "1GbE0-NSX Trunk"
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds01.id
  vlan_range {
    min_vlan = 0
    max_vlan = 4094
  }
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg01" {
  name                            = "10GbE0-Physical Management"
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 3
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg02" {
  name                            = "10GbE0-iSCSI"
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 4
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg03" {
  name                            = "10GbE0-vMotion"
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 5
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg04" {
  name                            = "10GbE0-Virtual Management"
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 6
  port_config_reset_at_disconnect = true
}

resource "vsphere_nas_datastore" "datastore01" {
  name = "vSphere NFS"
  host_system_ids = [for host in vsphere_host.hosts : host.id]
  type          = "NFS41"
  security_type = "AUTH_SYS"
  remote_hosts = [
    "10.0.1.130",
    "10.0.1.131",
    "10.0.1.132",
    "10.0.1.133",
  ]
  remote_path = "/mnt/Homelab/vSphere_NFS"
}