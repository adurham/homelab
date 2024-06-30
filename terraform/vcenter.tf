resource "vsphere_license" "licenseKey" {
  license_key = var.vcenter_license
}

resource "vsphere_datacenter" "Homelab" {
  name = "Homelab"
}

data "vsphere_host_thumbprint" "amd-hwvm01_thumbprint" {
  address  = "10.0.1.72"
  insecure = true
}

resource "vsphere_host" "amd-hwvm01" {
  hostname        = "amd-hwvm01.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm01_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_7_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm02_thumbprint" {
  address  = "10.0.1.73"
  insecure = true
}

resource "vsphere_host" "amd-hwvm02" {
  hostname        = "amd-hwvm02.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm02_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_7_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm03_thumbprint" {
  address  = "10.0.1.74"
  insecure = true
}

resource "vsphere_host" "amd-hwvm03" {
  hostname        = "amd-hwvm03.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm03_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_7_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm04_thumbprint" {
  address  = "10.0.1.75"
  insecure = true
}

resource "vsphere_host" "amd-hwvm04" {
  hostname        = "amd-hwvm04.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm04_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_7_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

resource "vsphere_compute_cluster" "cl01" {
  name = "amd-vmcl01"
  depends_on = [
    vsphere_datacenter.Homelab,
    vsphere_host.amd-hwvm01,
    vsphere_host.amd-hwvm02,
    vsphere_host.amd-hwvm03,
    vsphere_host.amd-hwvm04
  ]
  datacenter_id                = vsphere_datacenter.Homelab.moid
  drs_enabled                  = true
  drs_automation_level         = "fullyAutomated"
  ha_enabled                   = false
  dpm_enabled                  = false
  dpm_automation_level         = "automated"
  drs_scale_descendants_shares = "scaleCpuAndMemoryShares"
  drs_migration_threshold      = 2
  host_system_ids = [
    vsphere_host.amd-hwvm01.id,
    vsphere_host.amd-hwvm02.id,
    vsphere_host.amd-hwvm03.id,
    vsphere_host.amd-hwvm04.id
  ]
}

data "vsphere_host_thumbprint" "amd-hwvm05_thumbprint" {
  address  = "10.0.1.76"
  insecure = true
}

resource "vsphere_host" "amd-hwvm05" {
  hostname        = "amd-hwvm05.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm05_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_8_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm06_thumbprint" {
  address  = "10.0.1.77"
  insecure = true
}

resource "vsphere_host" "amd-hwvm06" {
  hostname        = "amd-hwvm06.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm06_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_8_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm07_thumbprint" {
  address  = "10.0.1.78"
  insecure = true
}

resource "vsphere_host" "amd-hwvm07" {
  hostname        = "amd-hwvm07.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm07_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_8_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

data "vsphere_host_thumbprint" "amd-hwvm08_thumbprint" {
  address  = "10.0.1.79"
  insecure = true
}

resource "vsphere_host" "amd-hwvm08" {
  hostname        = "amd-hwvm08.lab.amd-e.com"
  thumbprint      = data.vsphere_host_thumbprint.amd-hwvm08_thumbprint.id
  username        = "root"
  password        = var.esxi_password
  license         = var.esxi_8_license
  datacenter      = vsphere_datacenter.Homelab.moid
  cluster_managed = true
  lockdown        = "normal"
}

resource "vsphere_compute_cluster" "cl02" {
  name = "amd-vmcl02"
  depends_on = [
    vsphere_datacenter.Homelab,
    vsphere_host.amd-hwvm05,
    vsphere_host.amd-hwvm06,
    vsphere_host.amd-hwvm07,
    vsphere_host.amd-hwvm08
  ]
  datacenter_id                = vsphere_datacenter.Homelab.moid
  drs_enabled                  = true
  drs_automation_level         = "fullyAutomated"
  ha_enabled                   = true
  dpm_enabled                  = false
  dpm_automation_level         = "automated"
  drs_scale_descendants_shares = "scaleCpuAndMemoryShares"
  host_system_ids = [
    vsphere_host.amd-hwvm05.id,
    vsphere_host.amd-hwvm06.id,
    vsphere_host.amd-hwvm07.id,
    vsphere_host.amd-hwvm08.id
  ]
  vsan_enabled                  = true
  vsan_performance_enabled      = true
  vsan_unmap_enabled            = true
  vsan_esa_enabled              = true
  ha_datastore_apd_response     = "restartConservative"
  ha_datastore_pdl_response     = "restartAggressive"
  ha_heartbeat_datastore_policy = "allFeasibleDs"
}

resource "vsphere_distributed_virtual_switch" "vds01" {
  name = "1GbE0"
  depends_on = [
    vsphere_compute_cluster.cl01,
    vsphere_compute_cluster.cl02
  ]
  datacenter_id                    = vsphere_datacenter.Homelab.moid
  uplinks                          = ["Uplink 1", "Uplink 2"]
  active_uplinks                   = ["Uplink 1", "Uplink 2"]
  standby_uplinks                  = []
  netflow_sampling_rate            = 4096
  network_resource_control_enabled = true
  dynamic "host" {
    for_each = toset(vsphere_compute_cluster.cl01.host_system_ids)
    content {
      host_system_id = host.value
      devices        = ["vmnic0", "vmnic1"]
    }
  }
  dynamic "host" {
    for_each = toset(vsphere_compute_cluster.cl02.host_system_ids)
    content {
      host_system_id = host.value
      devices        = ["vmnic0", "vmnic1"]
    }
  }
}

resource "vsphere_distributed_virtual_switch" "vds02" {
  name = "10GbE0"
  depends_on = [
    vsphere_compute_cluster.cl01,
    vsphere_compute_cluster.cl02
  ]
  datacenter_id                    = vsphere_datacenter.Homelab.moid
  uplinks                          = ["Uplink 1", "Uplink 2"]
  active_uplinks                   = ["Uplink 1", "Uplink 2"]
  standby_uplinks                  = []
  netflow_sampling_rate            = 4096
  network_resource_control_enabled = true
  dynamic "host" {
    for_each = toset(vsphere_compute_cluster.cl01.host_system_ids)
    content {
      host_system_id = host.value
      devices        = ["vmnic2", "vmnic3"]
    }
  }
  dynamic "host" {
    for_each = toset(vsphere_compute_cluster.cl02.host_system_ids)
    content {
      host_system_id = host.value
      devices        = ["vmnic2", "vmnic3"]
    }
  }
}

resource "vsphere_distributed_port_group" "vds01_vdpg01" {
  name                            = "1GbE0-NSX Trunk"
  depends_on                      = [vsphere_distributed_virtual_switch.vds01]
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds01.id
  vlan_range {
    min_vlan = 0
    max_vlan = 4094
  }
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg01" {
  name                            = "10GbE0-Physical Management"
  depends_on                      = [vsphere_distributed_virtual_switch.vds02]
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 3
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg02" {
  name                            = "10GbE0-iSCSI"
  depends_on                      = [vsphere_distributed_virtual_switch.vds02]
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 4
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg03" {
  name                            = "10GbE0-vMotion"
  depends_on                      = [vsphere_distributed_virtual_switch.vds02]
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 5
  port_config_reset_at_disconnect = true
}

resource "vsphere_distributed_port_group" "vds02_vdpg04" {
  name                            = "10GbE0-Virtual Management"
  depends_on                      = [vsphere_distributed_virtual_switch.vds02]
  distributed_virtual_switch_uuid = vsphere_distributed_virtual_switch.vds02.id
  vlan_id                         = 6
  port_config_reset_at_disconnect = true
}

resource "vsphere_nas_datastore" "datastore01" {
  name = "vSphere NFS"
  host_system_ids = flatten([
    vsphere_compute_cluster.cl01.host_system_ids,
    vsphere_compute_cluster.cl02.host_system_ids
  ])
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
