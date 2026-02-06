#!/bin/bash
VMID=9002
ADMIN_PASS="Password123!"

# Define XML Content
cat > /tmp/Unattend.xml <<EOF
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
    <settings pass="oobeSystem">
        <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <InputLocale>en-US</InputLocale>
            <SystemLocale>en-US</SystemLocale>
            <UILanguage>en-US</UILanguage>
            <UserLocale>en-US</UserLocale>
        </component>
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <AutoLogon>
                <Password>
                    <Value>${ADMIN_PASS}</Value>
                    <PlainText>true</PlainText>
                </Password>
                <Enabled>true</Enabled>
                <LogonCount>1</LogonCount>
                <Username>Administrator</Username>
            </AutoLogon>
            <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HideLocalAccountScreen>true</HideLocalAccountScreen>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                <ProtectYourPC>3</ProtectYourPC>
            </OOBE>
            <UserAccounts>
                <AdministratorPassword>
                    <Value>${ADMIN_PASS}</Value>
                    <PlainText>true</PlainText>
                </AdministratorPassword>
            </UserAccounts>
            <FirstLogonCommands>
                <SynchronousCommand wcm:action="add">
                    <Order>1</Order>
                    <Description>Set Network Location to Private</Description>
                    <CommandLine>powershell -Command "Set-NetConnectionProfile -NetworkCategory Private"</CommandLine>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>2</Order>
                    <Description>Enable WinRM</Description>
                    <CommandLine>powershell -ExecutionPolicy ByPass -File C:\enable_winrm.ps1</CommandLine>
                </SynchronousCommand>
            </FirstLogonCommands>
        </component>
    </settings>
</unattend>
EOF

echo "Pushing Unattend.xml to VM $VMID..."

# Ensure directory exists (Panther should exist, but good to check)
qm guest exec $VMID cmd -- /c "mkdir C:\\Windows\\Panther" >/dev/null 2>&1

# Push file line by line
DEST="C:\\Windows\\Panther\\Unattend.xml"
qm guest exec $VMID cmd -- /c "echo. > $DEST"

while IFS= read -r line; do
    if [ ! -z "$line" ]; then
        # Escape special XML chars if needed for powershell, but Add-Content handles simple strings well.
        # However, single quotes need escaping for the powershell wrapper.
        ESCAPED_LINE=$(echo "$line" | sed "s/'/''/g")
        qm guest exec $VMID powershell -- -Command "Add-Content -Path '$DEST' -Value '$ESCAPED_LINE'" >/dev/null
    fi
done < "/tmp/Unattend.xml"

echo "Injection Complete."
