# Load VMware PowerCLI
Import-Module VMware.PowerCLI

# Import credentials from the secure file
$cred = Import-Clixml -Path "SecureCredentials.xml"

# Connect to vCenter Server
$vcenter = "amd-vmvc01.lab.amd-e.com"
Connect-VIServer -Server $vcenter -Credential $cred

# List all VMs on the vSphere cluster and gracefully shut them down
$clusterName = "amd-vmcl01"
$cluster = Get-Cluster -Name $clusterName
$vms = Get-VM -Location $cluster

foreach ($vm in $vms) {
    Shutdown-VMGuest -VM $vm -Confirm:$false
}

# Wait for all VMs to shut down with a maximum wait time of 10 minutes
$maxWaitTime = 600  # Maximum wait time in seconds (10 minutes)
$startTime = Get-Date
while (($vms | Get-VM | Where-Object { $_.PowerState -ne "PoweredOff" }).Count -gt 0 -and ((Get-Date) - $startTime).TotalSeconds -lt $maxWaitTime) {
    Start-Sleep -Seconds 10
}

# Disable vSphere HA
$cluster | Get-Cluster | Set-Cluster -HAEnabled:$false -Confirm:$false

# Set vCLS mode to retreat
$vc = Get-View -Id $cluster.ExtensionData.Parent
$vcExtensionManager = Get-View ExtensionManager
$vcExtensionManager.UpdateViewData()
$vcRetreatMode = $vcExtensionManager.ExtensionList | Where-Object {$_.Key -eq "com.vmware.vim.eam"}
$vcRetreatMode.SetClusterMode($cluster.ExtensionData.MoRef, "retreat")

# Get all hosts in the cluster
$hosts = Get-Cluster -Name $clusterName | Get-VMHost

# Set maintenance mode on hosts 2, 3, and 4 and shut them down
$hostsToMaintain = $hosts[1..3]

foreach ($host in $hostsToMaintain) {
    Set-VMHost -VMHost $host -State Maintenance -Confirm:$false
}

# Wait for the hosts to enter maintenance mode with a maximum wait time of 10 minutes
$maxWaitTime = 600  # Maximum wait time in seconds (10 minutes)
$startTime = Get-Date
while (($hostsToMaintain | Get-VMHost | Where-Object { $_.ConnectionState -ne "Maintenance" }).Count -gt 0 -and ((Get-Date) - $startTime).TotalSeconds -lt $maxWaitTime) {
    Start-Sleep -Seconds 10
}

# Shut down the 3 hosts
foreach ($host in $hostsToMaintain) {
    Stop-VMHost -VMHost $host -Confirm:$false
}

# Set maintenance mode on the first host without moving anything and shut it down
$firstHost = $hosts[0]
Set-VMHost -VMHost $firstHost -State Maintenance -Evacuate:$false -Confirm:$false
Stop-VMHost -VMHost $firstHost -Confirm:$false

# Disconnect from vCenter Server
Disconnect-VIServer -Server $vcenter -Confirm:$false
