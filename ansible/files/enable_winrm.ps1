# Enable WinRM for Ansible
$ErrorActionPreference = "Stop"

Write-Host "Enabling PS Remoting..."
Enable-PSRemoting -Force

Write-Host "Configuring Basic Auth..."
Set-Item -Path WSMan:\localhost\Service\Auth\Basic -Value $true

Write-Host "Configuring AllowUnencrypted..."
Set-Item -Path WSMan:\localhost\Service\AllowUnencrypted -Value $true

Write-Host "Configuring TrustedHosts..."
Set-Item WSMan:\localhost\Client\TrustedHosts -Value * -Force

Write-Host "Restarting WinRM Service..."
Restart-Service WinRM

Write-Host "WinRM Configuration Complete."
