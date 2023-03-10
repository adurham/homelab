#version=RHEL8
# Sustem lanquage
lang en_US.UTF-8
# Keyboard layouts
keyboard --xlayouts= 'us'
# System timezone
timezone America/New_York --utc
# Use text installer
text
# Reboot when done
reboot
# Use CDROM installation media
cdrom
# Network information
network --hostname=localhost --bootproto=dhcp --device=ens192 --onboot=yes --ipv6=auto --activate
# Configure Firewall
firewall --enabled --ssh
# Don't run the Setup Agent on first boot
firstboot --disable
# Configure SELinux
selinux --enforcing
# Don't configure X
skipx
# Disk partitioning information
ignoredisk --only-use=sda
clearpart --none --initlabel
bootloader  --location=boot --boot-drive=sda --append="rd.plymouth=0 plymouth.enable=0 crashkernel=auto pti=on vsyscall=none page_poison=1 slub_debug=P audit=1 audit_backlog_limit=8192" --iscrypted --password=${hashed_grub_password}
part /boot/efi --fstype=efi --size=1024 --asprimary --ondisk=sda
part /boot --fstype=ext4 --size=1024 --asprimary --ondisk=sda
part swap --fstype="swap" --size=1024 --ondisk=sda
part pv.01 --grow --ondisk=sda
volgroup vg01 pv.01
logvol /home --fstype=ext4 --name=lv_home --vgname=vg01 --size=4096
logvol /tmp --fstype=ext4 --name=lv_tmp --vgname=vg01 --size=1024
logvol /var --fstype=ext4 --name=lv_var --vgname=vg01 --size=1024
logvol /var/log --fstype=ext4 --name=lv_var_log --vgname=vg01 --size=1024
logvol /var/log/audit --fstype=ext4 --name=lv_var_log_audit --vgname=vg01 --size=1024
logvol /var/tmp --fstype=ext4 --name=lv_var_tmp --vgname=vg01 --size=1024
logvol / --fstype=ext4 --name=lv_root --vgname=vg01 --grow --percent=100
# Install Packages
%packages
@^server-product-environment
aide
audit
fapolicyd
firewalld
opensc
openscap
openscap-scanner
openssh-server
openssl-pkcs11
policycoreutils
postfix
rng-tools
rsyslog
rsyslog-gnutls
scap-security-guide
tmux
usbguard
-abrt
-abrt-addon-ccpp
-abrt-addon-kerneloops
-abrt-cli
-abrt-plugin-sosreport
-iprutils
-krb5-server
-krb5-workstation
-libreport-plugin-logger
-libreport-plugin-rhtsupport
-python3-abrt-addon
-rsh-server
-sendmail
-telet-server
-tftp-server
-tuned
-usfted
-xorg-x11-server-Xorg
-xorq-x11-server-Xwayland
-xorq-x11-server-common
-xorg-x11-server-utils anaconda-ks.cfa
%end
# Lock the root account
rootpw --lock
# Setup Users
user --groups=wheel --name=admin --password=${hashed_admin_password} --iscrypted --gecos="Admin"
sshkey --username=admin "${ssh_publickey}"
user --groups=wheel --name=packer --password=${hashed_packer_password} --iscrypted --gecos="Packer"
sshkey --username=packer "${ssh_publickey}"
# Set Password Policy
%anaconda
pwpolicy root --minlen=6 --minquality=1 --notstrict --nochanges --notempty
pwpolicy user --minlen=6 --minquality=1 --notstrict --nochanges --notempty
pwpolicy luks --minlen=6 --minquality=1 --notstrict --nochanges --notempty
%end
# Configure kdump kernel crash dumping mechanism
%addon com_redhat_kdump --disable --reserve-mb='auto'
%end
# Set Security Profile
%addon org_ fedora_oscap
    content-tupe = scap-security-quide
    datastream-id = scap_org.open-scap_datastream_from_xccdf_ssg-rhe18-xccdf-1.2.xml
    xccdf-id = scap_org.open-scap_cref_ssy-rhe18-xccdf-1.2.xml
    profile = xccdf_org.ssyproject.content_profile_stig
%end
# Use SSSD
%post
authselect select --force sssd
authselect enable-feature with-smartcard
authselect enable-feature without-nullok
authselect apply-changes -b
%end
# Write auditd rules
%post
cat <<EOF > /etc/audit/rules.d/stig.rules
-a always,exit -F arch=b32 -S chmod -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S chmod -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S chown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S chown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fchmod -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fchmod -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fchmodat -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fchmodat -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fchown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fchown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fchownat -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fchownat -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fremovexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fremovexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S fremovexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fremovexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b32 -S fsetxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S fsetxattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S fsetxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S fsetxattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b32 -S lchown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S lchown -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S lremovexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S lremovexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S lremovexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S lremovexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b32 -S lsetxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S lsetxattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S lsetxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S lsetxattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b32 -S removexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S removexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S removexattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S removexattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b32 -S setxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b32 -S setxattr -F auid=0 -F key=perm_mod
-a always,exit -F arch=b64 -S setxattr -F auid>=1000 -F auid!=unset -F key=perm_mod
-a always,exit -F arch=b64 -S setxattr -F auid=0 -F key=perm_mod
-a always,exit -F path=/usr/bin/chacl -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/setfacl -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/chcon -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/semanage -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/setfiles -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/setsebool -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F arch=b32 -S rename -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b64 -S rename -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b32 -S renameat -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b64 -S renameat -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b32 -S rmdir -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b64 -S rmdir -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b32 -S unlink -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b64 -S unlink -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b32 -S unlinkat -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b64 -S unlinkat -F auid>=1000 -F auid!=unset -F key=delete
-a always,exit -F arch=b32 -S creat -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S creat -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S creat -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S creat -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S ftruncate -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S ftruncate -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S ftruncate -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S ftruncate -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S open -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S open -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S open -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S open -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S open_by_handle_at -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S open_by_handle_at -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S open_by_handle_at -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S open_by_handle_at -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S openat -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S openat -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S openat -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S openat -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S truncate -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S truncate -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S truncate -F exit=-EACCES -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b64 -S truncate -F exit=-EPERM -F auid>=1000 -F auid!=unset -F key=access
-a always,exit -F arch=b32 -S delete_module -F auid>=1000 -F auid!=unset -F key=modules
-a always,exit -F arch=b64 -S delete_module -F auid>=1000 -F auid!=unset -F key=modules
-a always,exit -F arch=b32 -S finit_module -F auid>=1000 -F auid!=unset -F key=modules
-a always,exit -F arch=b64 -S finit_module -F auid>=1000 -F auid!=unset -F key=modules
-a always,exit -F arch=b32 -S init_module -F auid>=1000 -F auid!=unset -F key=modules
-a always,exit -F arch=b64 -S init_module -F auid>=1000 -F auid!=unset -F key=modules
-w /var/log/lastlog -p wa -k logins
-a always,exit -F path=/usr/bin/chage -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/chsh -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/crontab -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/gpasswd -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/kmod -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/mount -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/newgrp -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/pam_timestamp_check -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/passwd -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/postdrop -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/postqueue -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/ssh-agent -F perm=x -F auid>=1000 -F auid!=unset -k privileged-ssh-agent
-a always,exit -F path=/usr/libexec/openssh/ssh-keysign -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/su -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/sudo -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/bin/umount -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/unix_chkpwd -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/unix_update -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/userhelper -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-a always,exit -F path=/usr/sbin/usermod -F perm=x -F auid>=1000 -F auid!=unset -F key=privileged
-e 2
-a always,exit -F arch=b32 -S mount -F auid>=1000 -F auid!=unset -F key=export
-a always,exit -F arch=b64 -S mount -F auid>=1000 -F auid!=unset -F key=export
-w /etc/sudoers -p wa -k actions
-w /etc/sudoers.d/ -p wa -k actions
-a always,exit -F arch=b32 -S execve -C uid!=euid -F euid=0 -k setuid
-a always,exit -F arch=b64 -S execve -C uid!=euid -F euid=0 -k setuid
-a always,exit -F arch=b32 -S execve -C gid!=egid -F egid=0 -k setgid
-a always,exit -F arch=b64 -S execve -C gid!=egid -F egid=0 -k setgid
-w /etc/group -p wa -k audit_rules_usergroup_modification
-w /etc/gshadow -p wa -k audit_rules_usergroup_modification
-w /etc/security/opasswd -p wa -k audit_rules_usergroup_modification
-w /etc/passwd -p wa -k audit_rules_usergroup_modification
-w /etc/shadow -p wa -k audit_rules_usergroup_modification
EOF
chmod 0640 /etc/audit/rules.d/*.rules
%end

##### STIG Items
%post
#### System Settings
### Installing and Maintaining Control
## System and Software Integrity
# Configure AIDE to Verify the Audit Tools
if grep -i '^.*/usr/sbin/auditctl.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/auditctl.*#/usr/sbin/auditctl p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/auditctl p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/auditd.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/auditd.*#/usr/sbin/auditd p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/auditd p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/ausearch.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/ausearch.*#/usr/sbin/ausearch p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/ausearch p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/aureport.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/aureport.*#/usr/sbin/aureport p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/aureport p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/autrace.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/autrace.*#/usr/sbin/autrace p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/autrace p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/augenrules.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/augenrules.*#/usr/sbin/augenrules p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/augenrules p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
if grep -i '^.*/usr/sbin/rsyslogd.*$' /etc/aide.conf; then
sed -i "s#.*/usr/sbin/rsyslogd.*#/usr/sbin/rsyslogd p+i+n+u+g+s+b+acl+xattrs+sha512
#" /etc/aide.conf
else
echo "/usr/sbin/rsyslogd p+i+n+u+g+s+b+acl+xattrs+sha512
" >> /etc/aide.conf
fi
# Configure Notification of Post-AIDE Scan Details
var_aide_scan_notification_email='root@localhost'
CRONTAB=/etc/crontab
CRONDIRS='/etc/cron.d /etc/cron.daily /etc/cron.weekly /etc/cron.monthly'
if [ -f /etc/crontab ]; then
	CRONTAB_EXIST=/etc/crontab
fi
if [ -f /var/spool/cron/root ]; then
	VARSPOOL=/var/spool/cron/root
fi
if ! grep -qR '^.*/usr/sbin/aide\s*\-\-check.*|.*\/bin\/mail\s*-s\s*".*"\s*.*@.*$' $CRONTAB_EXIST $VARSPOOL $CRONDIRS; then
	echo "0 5 * * * root /usr/sbin/aide  --check | /bin/mail -s \"\$(hostname) - AIDE Integrity Check\" $var_aide_scan_notification_email" >> $CRONTAB
fi
# Configure AIDE to Verify Access Control Lists (ACLs)
aide_conf="/etc/aide.conf"
groups=$(LC_ALL=C grep "^[A-Z][A-Za-z_]*" $aide_conf | grep -v "^ALLXTRAHASHES" | cut -f1 -d '=' | tr -d ' ' | sort -u)
for group in $groups
do
	config=$(grep "^$group\s*=" $aide_conf | cut -f2 -d '=' | tr -d ' ')
	if ! [[ $config = *acl* ]]
	then
		if [[ -z $config ]]
		then
			config="acl"
		else
			config=$config"+acl"
		fi
	fi
	sed -i "s/^$group\s*=.*/$group = $config/g" $aide_conf
done
# Configure AIDE to Verify Extended Attributes
aide_conf="/etc/aide.conf"
groups=$(LC_ALL=C grep "^[A-Z][A-Za-z_]*" $aide_conf | grep -v "^ALLXTRAHASHES" | cut -f1 -d '=' | tr -d ' ' | sort -u)
for group in $groups
do
	config=$(grep "^$group\s*=" $aide_conf | cut -f2 -d '=' | tr -d ' ')
	if ! [[ $config = *xattrs* ]]
	then
		if [[ -z $config ]]
		then
			config="xattrs"
		else
			config=$config"+xattrs"
		fi
	fi
	sed -i "s/^$group\s*=.*/$group = $config/g" $aide_conf
done
# Enable FIPS mode
fips-mode-setup --enable
# Configure GnuTLS library to use DoD-approved TLS Encryption
CONF_FILE=/etc/crypto-policies/back-ends/gnutls.config
correct_value='+VERS-ALL:-VERS-DTLS0.9:-VERS-SSL3.0:-VERS-TLS1.0:-VERS-TLS1.1:-VERS-DTLS1.0'
grep -q $${correct_value} $${CONF_FILE}
if [[ $? -ne 0 ]]; then
    existing_value=$(grep -Po '(\+VERS-ALL(?::-VERS-[A-Z]+\d\.\d)+)' $${CONF_FILE})
    if [[ ! -z $${existing_value} ]]; then
        sed -i "s/$${existing_value}/$${correct_value}/g" $${CONF_FILE}
    else
        echo $${correct_value} >> $${CONF_FILE}
    fi
fi
# Configure SSH Client to Use FIPS 140-2 Validated Ciphers
sshd_approved_ciphers='aes256-ctr,aes192-ctr,aes128-ctr'
LC_ALL=C sed -i "/^.*Ciphers\s\+/d" "/etc/crypto-policies/back-ends/openssh.config"
echo "Ciphers $${sshd_approved_ciphers}" >> "/etc/crypto-policies/back-ends/openssh.config"
CONF_FILE=/etc/crypto-policies/back-ends/opensshserver.config
correct_value="-oCiphers=$${sshd_approved_ciphers}"
# Ensure CRYPTO_POLICY is not commented out
sed -i 's/#CRYPTO_POLICY=/CRYPTO_POLICY=/' $${CONF_FILE}
grep -q "'$${correct_value}'" $${CONF_FILE}
if [[ $? -ne 0 ]]; then
    existing_value=$(grep -Po '(-oCiphers=\S+)' $${CONF_FILE})
    if [[ ! -z $${existing_value} ]]; then
        sed -i "s/$${existing_value}/$${correct_value}/g" $${CONF_FILE}
    else
        echo "CRYPTO_POLICY='$${correct_value}'" >> $${CONF_FILE}
    fi
fi
# Configure SSH Client to Use FIPS 140-2 Validated MACs
sshd_approved_macs='hmac-sha2-512,hmac-sha2-256'
LC_ALL=C sed -i "/^.*MACs\s\+/d" "/etc/crypto-policies/back-ends/openssh.config"
echo "MACs $${sshd_approved_macs}" >> "/etc/crypto-policies/back-ends/openssh.config"
CONF_FILE=/etc/crypto-policies/back-ends/opensshserver.config
correct_value="-oMACs=$${sshd_approved_macs}"
sed -i 's/#CRYPTO_POLICY=/CRYPTO_POLICY=/' $${CONF_FILE}
grep -q "'$${correct_value}'" $${CONF_FILE}
if [[ $? -ne 0 ]]; then
    existing_value=$(grep -Po '(-oMACs=\S+)' $${CONF_FILE})
    if [[ ! -z $${existing_value} ]]; then
        sed -i "s/$${existing_value}/$${correct_value}/g" $${CONF_FILE}
    else
        echo "CRYPTO_POLICY='$${correct_value}'" >> $${CONF_FILE}
    fi
fi
## Disk Partioning
# N/A
## Sudo
# Ensure Users Re-Authenticate for Privilege Escalation - sudo NOPASSWD
for f in /etc/sudoers /etc/sudoers.d/* ; do
  if [ ! -e "$f" ] ; then
    continue
  fi
  matching_list=$(grep -P '^(?!#).*[\s]+NOPASSWD[\s]*\:.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      sed -i "s/^$${entry}$/# &/g" $f
    done <<< "$matching_list"
    /usr/sbin/visudo -cf $f &> /dev/null || echo "Fail to validate $f with visudo"
  fi
done
# Ensure sudo timestamp_timeout is appropriate
var_sudo_timestamp_timeout='30'
if grep -x '^[\s]*Defaults.*\btimestamp_timeout=.*' /etc/sudoers.d/*; then
    find /etc/sudoers.d/ -type f -exec sed -i "/^[\s]*Defaults.*\btimestamp_timeout=.*/d" {} \;
fi
cp /etc/sudoers /etc/sudoers.bak
if ! grep -P '^[\s]*Defaults.*\btimestamp_timeout=[-]?\w+\b\b.*$' /etc/sudoers; then
    echo "Defaults timestamp_timeout=$${var_sudo_timestamp_timeout}" >> /etc/sudoers
else
    if ! grep -P "^[\s]*Defaults.*\btimestamp_timeout=$${var_sudo_timestamp_timeout}\b.*$" /etc/sudoers; then
        
        sed -Ei "s/(^[\s]*Defaults.*\btimestamp_timeout=)[-]?\w+(\b.*$)/\1$${var_sudo_timestamp_timeout}\2/" /etc/sudoers
    fi
fi
if /usr/sbin/visudo -qcf /etc/sudoers; then
    rm -f /etc/sudoers.bak
else
    echo "Fail to validate remediated /etc/sudoers, reverting to original file."
    mv /etc/sudoers.bak /etc/sudoers
    false
fi
# Ensure invoking users password for privilege escalation when using sudo
if grep -x '^Defaults !targetpw$' /etc/sudoers.d/*; then
    find /etc/sudoers.d/ -type f -exec sed -i "/Defaults !targetpw/d" {} \;
fi
if grep -x '^Defaults !rootpw$' /etc/sudoers.d/*; then
    find /etc/sudoers.d/ -type f -exec sed -i "/Defaults !rootpw/d" {} \;
fi
if grep -x '^Defaults !runaspw$' /etc/sudoers.d/*; then
    find /etc/sudoers.d/ -type f -exec sed -i "/Defaults !runaspw/d" {} \;
fi
LC_ALL=C sed -i "/Defaults !targetpw/d" "/etc/sudoers"
echo "Defaults !targetpw" >> "/etc/sudoers"
LC_ALL=C sed -i "/Defaults !rootpw/d" "/etc/sudoers"
echo "Defaults !rootpw" >> "/etc/sudoers"
LC_ALL=C sed -i "/Defaults !runaspw/d" "/etc/sudoers"
echo "Defaults !runaspw" >> "/etc/sudoers"
## System Tooling / Utilites
# N/A
## Updating Software
# Ensure gpgcheck Enabled for Local Packages
echo "localpkg_gpgcheck=1" >> /etc/yum.conf
### Account and Access Control
## Warning Banners for System Access
# Modify the System Login Banner
login_banner_text='^(You[\s\n]+are[\s\n]+accessing[\s\n]+a[\s\n]+U\.S\.[\s\n]+Government[\s\n]+\(USG\)[\s\n]+Information[\s\n]+System[\s\n]+\(IS\)[\s\n]+that[\s\n]+is[\s\n]+provided[\s\n]+for[\s\n]+USG\-authorized[\s\n]+use[\s\n]+only\.[\s\n]+By[\s\n]+using[\s\n]+this[\s\n]+IS[\s\n]+\(which[\s\n]+includes[\s\n]+any[\s\n]+device[\s\n]+attached[\s\n]+to[\s\n]+this[\s\n]+IS\)\,[\s\n]+you[\s\n]+consent[\s\n]+to[\s\n]+the[\s\n]+following[\s\n]+conditions\:(?:[\n]+|(?:\\n)+)\-The[\s\n]+USG[\s\n]+routinely[\s\n]+intercepts[\s\n]+and[\s\n]+monitors[\s\n]+communications[\s\n]+on[\s\n]+this[\s\n]+IS[\s\n]+for[\s\n]+purposes[\s\n]+including\,[\s\n]+but[\s\n]+not[\s\n]+limited[\s\n]+to\,[\s\n]+penetration[\s\n]+testing\,[\s\n]+COMSEC[\s\n]+monitoring\,[\s\n]+network[\s\n]+operations[\s\n]+and[\s\n]+defense\,[\s\n]+personnel[\s\n]+misconduct[\s\n]+\(PM\)\,[\s\n]+law[\s\n]+enforcement[\s\n]+\(LE\)\,[\s\n]+and[\s\n]+counterintelligence[\s\n]+\(CI\)[\s\n]+investigations\.(?:[\n]+|(?:\\n)+)\-At[\s\n]+any[\s\n]+time\,[\s\n]+the[\s\n]+USG[\s\n]+may[\s\n]+inspect[\s\n]+and[\s\n]+seize[\s\n]+data[\s\n]+stored[\s\n]+on[\s\n]+this[\s\n]+IS\.(?:[\n]+|(?:\\n)+)\-Communications[\s\n]+using\,[\s\n]+or[\s\n]+data[\s\n]+stored[\s\n]+on\,[\s\n]+this[\s\n]+IS[\s\n]+are[\s\n]+not[\s\n]+private\,[\s\n]+are[\s\n]+subject[\s\n]+to[\s\n]+routine[\s\n]+monitoring\,[\s\n]+interception\,[\s\n]+and[\s\n]+search\,[\s\n]+and[\s\n]+may[\s\n]+be[\s\n]+disclosed[\s\n]+or[\s\n]+used[\s\n]+for[\s\n]+any[\s\n]+USG\-authorized[\s\n]+purpose\.(?:[\n]+|(?:\\n)+)\-This[\s\n]+IS[\s\n]+includes[\s\n]+security[\s\n]+measures[\s\n]+\(e\.g\.\,[\s\n]+authentication[\s\n]+and[\s\n]+access[\s\n]+controls\)[\s\n]+to[\s\n]+protect[\s\n]+USG[\s\n]+interests\-\-not[\s\n]+for[\s\n]+your[\s\n]+personal[\s\n]+benefit[\s\n]+or[\s\n]+privacy\.(?:[\n]+|(?:\\n)+)\-Notwithstanding[\s\n]+the[\s\n]+above\,[\s\n]+using[\s\n]+this[\s\n]+IS[\s\n]+does[\s\n]+not[\s\n]+constitute[\s\n]+consent[\s\n]+to[\s\n]+PM\,[\s\n]+LE[\s\n]+or[\s\n]+CI[\s\n]+investigative[\s\n]+searching[\s\n]+or[\s\n]+monitoring[\s\n]+of[\s\n]+the[\s\n]+content[\s\n]+of[\s\n]+privileged[\s\n]+communications\,[\s\n]+or[\s\n]+work[\s\n]+product\,[\s\n]+related[\s\n]+to[\s\n]+personal[\s\n]+representation[\s\n]+or[\s\n]+services[\s\n]+by[\s\n]+attorneys\,[\s\n]+psychotherapists\,[\s\n]+or[\s\n]+clergy\,[\s\n]+and[\s\n]+their[\s\n]+assistants\.[\s\n]+Such[\s\n]+communications[\s\n]+and[\s\n]+work[\s\n]+product[\s\n]+are[\s\n]+private[\s\n]+and[\s\n]+confidential\.[\s\n]+See[\s\n]+User[\s\n]+Agreement[\s\n]+for[\s\n]+details\.|I've[\s\n]+read[\s\n]+\&[\s\n]+consent[\s\n]+to[\s\n]+terms[\s\n]+in[\s\n]+IS[\s\n]+user[\s\n]+agreem't\.)$'
login_banner_text=$(echo "$login_banner_text" | sed 's/^\^\(.*\)\$$/\1/g')
login_banner_text=$(echo "$login_banner_text" | sed 's/^(\(.*\.\)|.*)$/\1/g')
login_banner_text=$(echo "$login_banner_text" | sed 's/\[\\s\\n\]+/ /g')
login_banner_text=$(echo "$login_banner_text" | sed 's/(?:\[\\n\]+|(?:\\\\n)+)/\n/g')
login_banner_text=$(echo "$login_banner_text" | sed 's/\\//g')
formatted=$(echo "$login_banner_text" | fold -sw 80)
cat <<EOF >/etc/issue
$formatted
EOF
## Protect Accounts by Configuring PAM
# Account lockouts must be logged
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
echo "
authselect integrity check failed. Remediation aborted!
This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
It is not recommended to manually edit the PAM files when authselect tool is available.
In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
exit 1
fi
authselect enable-feature with-faillock
authselect apply-changes -b
else
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
for pam_file in "$${AUTH_FILES[@]}"
do
    if ! grep -qE '^\s*auth\s+required\s+pam_faillock\.so\s+(preauth silent|authfail).*$' "$pam_file" ; then
        sed -i --follow-symlinks '/^auth.*sufficient.*pam_unix\.so.*/i auth        required      pam_faillock.so preauth silent' "$pam_file"
        sed -i --follow-symlinks '/^auth.*required.*pam_deny\.so.*/i auth        required      pam_faillock.so authfail' "$pam_file"
        sed -i --follow-symlinks '/^account.*required.*pam_unix\.so.*/i account     required      pam_faillock.so' "$pam_file"
    fi
    sed -Ei 's/(auth.*)(\[default=die\])(.*pam_faillock\.so)/\1required     \3/g' "$pam_file"
done
fi
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f $FAILLOCK_CONF ]; then
    regex="^\s*audit"
    line="audit"
    if ! grep -q $regex $FAILLOCK_CONF; then
        echo $line >> $FAILLOCK_CONF
    fi
    for pam_file in "$${AUTH_FILES[@]}"
    do
        if [ -e "$pam_file" ] ; then
            PAM_FILE_PATH="$pam_file"
            if [ -f /usr/bin/authselect ]; then
                if ! authselect check; then
                echo "
                authselect integrity check failed. Remediation aborted!
                This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
                It is not recommended to manually edit the PAM files when authselect tool is available.
                In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
                exit 1
                fi
                CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
                if [[ ! $CURRENT_PROFILE == custom/* ]]; then
                    ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
                    authselect create-profile hardening -b $CURRENT_PROFILE
                    CURRENT_PROFILE="custom/hardening"
                    authselect apply-changes -b --backup=before-hardening-custom-profile
                    authselect select $CURRENT_PROFILE
                    for feature in $ENABLED_FEATURES; do
                        authselect enable-feature $feature;
                    done
                    authselect apply-changes -b --backup=after-hardening-custom-profile
                fi
                PAM_FILE_NAME=$(basename "$pam_file")
                PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
                authselect apply-changes -b
            fi
        if grep -qP '^\s*auth\s.*\bpam_faillock.so\s.*\baudit\b' "$PAM_FILE_PATH"; then
            sed -i -E --follow-symlinks 's/(.*auth.*pam_faillock.so.*)\baudit\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
        fi
            if [ -f /usr/bin/authselect ]; then
                authselect apply-changes -b
            fi
        else
            echo "$pam_file was not found" >&2
        fi
    done
else
    for pam_file in "$${AUTH_FILES[@]}"
    do
        if ! grep -qE '^\s*auth.*pam_faillock\.so (preauth|authfail).*audit' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock\.so.*preauth.*silent.*/ s/$/ audit/' "$pam_file"
        fi
    done
fi
# Limit Password Reuse: password-auth
var_password_pam_remember='5'
var_password_pam_remember_control_flag='required'
PAM_FILE_PATH="/etc/pam.d/password-auth"
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
        authselect integrity check failed. Remediation aborted!
        This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
        It is not recommended to manually edit the PAM files when authselect tool is available.
        In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/password-auth")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if ! grep -qP '^\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s*.*' "$PAM_FILE_PATH"; then
    if [ "$(grep -cP '^\s*password\s+.*\s+pam_pwhistory.so\s*' "$PAM_FILE_PATH")" -eq 1 ]; then
        sed -i -E --follow-symlinks 's/^(\s*password\s+).*(\bpam_pwhistory.so.*)/\1'"$var_password_pam_remember_control_flag"' \2/' "$PAM_FILE_PATH"
    else
        sed -i --follow-symlinks '/^password.*requisite.*pam_pwquality.so/a password     '"$var_password_pam_remember_control_flag"'    pam_pwhistory.so' "$PAM_FILE_PATH"
    fi
fi
if ! grep -qP '^\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s*.*\sremember\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks '/\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so.*/ s/$/ remember='"$var_password_pam_remember"'/' "$PAM_FILE_PATH"
else
    sed -i -E --follow-symlinks 's/(\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s+.*)('"remember"'=)[[:alnum:]]+\s*(.*)/\1\2'"$var_password_pam_remember"' \3/' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
# Limit Password Reuse: system-auth
var_password_pam_remember='5'
var_password_pam_remember_control_flag='required'
PAM_FILE_PATH="/etc/pam.d/system-auth"
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
        authselect integrity check failed. Remediation aborted!
        This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
        It is not recommended to manually edit the PAM files when authselect tool is available.
        In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/system-auth")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if ! grep -qP '^\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s*.*' "$PAM_FILE_PATH"; then
    if [ "$(grep -cP '^\s*password\s+.*\s+pam_pwhistory.so\s*' "$PAM_FILE_PATH")" -eq 1 ]; then
        sed -i -E --follow-symlinks 's/^(\s*password\s+).*(\bpam_pwhistory.so.*)/\1'"$var_password_pam_remember_control_flag"' \2/' "$PAM_FILE_PATH"
    else
        sed -i --follow-symlinks '/^password.*requisite.*pam_pwquality.so/a password     '"$var_password_pam_remember_control_flag"'    pam_pwhistory.so' "$PAM_FILE_PATH"
    fi
fi
if ! grep -qP '^\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s*.*\sremember\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks '/\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so.*/ s/$/ remember='"$var_password_pam_remember"'/' "$PAM_FILE_PATH"
else
    sed -i -E --follow-symlinks 's/(\s*password\s+'"$var_password_pam_remember_control_flag"'\s+pam_pwhistory.so\s+.*)('"remember"'=)[[:alnum:]]+\s*(.*)/\1\2'"$var_password_pam_remember"' \3/' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
# Lock Accounts After Failed Password Attempts
var_accounts_passwords_pam_faillock_deny='3'
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
authselect integrity check failed. Remediation aborted!
This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
It is not recommended to manually edit the PAM files when authselect tool is available.
In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    authselect enable-feature with-faillock
    authselect apply-changes -b
else
    AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth\s+required\s+pam_faillock\.so\s+(preauth silent|authfail).*$' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*sufficient.*pam_unix.so.*/i auth        required      pam_faillock.so preauth silent' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_deny.so.*/i auth        required      pam_faillock.so authfail' "$pam_file"
            sed -i --follow-symlinks '/^account.*required.*pam_unix.so.*/i account     required      pam_faillock.so' "$pam_file"
        fi
        sed -Ei 's/(auth.*)(\[default=die\])(.*pam_faillock.so)/\1required     \3/g' "$pam_file"
    done
fi
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f $FAILLOCK_CONF ]; then
    regex="^\s*deny\s*="
    line="deny = $var_accounts_passwords_pam_faillock_deny"
    if ! grep -q $regex $FAILLOCK_CONF; then
        echo $line >>$FAILLOCK_CONF
    else
        sed -i --follow-symlinks 's|^\s*\(deny\s*=\s*\)\(\S\+\)|\1'"$var_accounts_passwords_pam_faillock_deny"'|g' $FAILLOCK_CONF
    fi
    for pam_file in "$${AUTH_FILES[@]}"; do
        if [ -e "$pam_file" ]; then
            PAM_FILE_PATH="$pam_file"
            if [ -f /usr/bin/authselect ]; then
                if ! authselect check; then
                    echo "
                    authselect integrity check failed. Remediation aborted!
                    This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
                    It is not recommended to manually edit the PAM files when authselect tool is available.
                    In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
                    exit 1
                fi
                CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
                if [[ ! $CURRENT_PROFILE == custom/* ]]; then
                    ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
                    authselect create-profile hardening -b $CURRENT_PROFILE
                    CURRENT_PROFILE="custom/hardening"
                    authselect apply-changes -b --backup=before-hardening-custom-profile
                    authselect select $CURRENT_PROFILE
                    for feature in $ENABLED_FEATURES; do
                        authselect enable-feature $feature
                    done
                    authselect apply-changes -b --backup=after-hardening-custom-profile
                fi
                PAM_FILE_NAME=$(basename "$pam_file")
                PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
                authselect apply-changes -b
            fi
            if grep -qP '^\s*auth\s.*\bpam_faillock.so\s.*\bdeny\b' "$PAM_FILE_PATH"; then
                sed -i -E --follow-symlinks 's/(.*auth.*pam_faillock.so.*)\bdeny\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
            fi
            if [ -f /usr/bin/authselect ]; then
                authselect apply-changes -b
            fi
        else
            echo "$pam_file was not found" >&2
        fi
    done
else
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth.*pam_faillock.so (preauth|authfail).*deny' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*preauth.*silent.*/ s/$/ deny='"$var_accounts_passwords_pam_faillock_deny"'/' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*authfail.*/ s/$/ deny='"$var_accounts_passwords_pam_faillock_deny"'/' "$pam_file"
        else
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*preauth.*silent.*\)\('"deny"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_deny"'\3/' "$pam_file"
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*authfail.*\)\('"deny"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_deny"'\3/' "$pam_file"
        fi
    done
fi
# Configure the root Account for Failed Password Attempts
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
authselect integrity check failed. Remediation aborted!
This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
It is not recommended to manually edit the PAM files when authselect tool is available.
In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    authselect enable-feature with-faillock
    authselect apply-changes -b
else
    AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth\s+required\s+pam_faillock\.so\s+(preauth silent|authfail).*$' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*sufficient.*pam_unix.so.*/i auth        required      pam_faillock.so preauth silent' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_deny.so.*/i auth        required      pam_faillock.so authfail' "$pam_file"
            sed -i --follow-symlinks '/^account.*required.*pam_unix.so.*/i account     required      pam_faillock.so' "$pam_file"
        fi
        sed -Ei 's/(auth.*)(\[default=die\])(.*pam_faillock.so)/\1required     \3/g' "$pam_file"
    done
fi
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f $FAILLOCK_CONF ]; then
    regex="^\s*even_deny_root"
    line="even_deny_root"
    if ! grep -q $regex $FAILLOCK_CONF; then
        echo $line >>$FAILLOCK_CONF
    fi
    for pam_file in "$${AUTH_FILES[@]}"; do
        if [ -e "$pam_file" ]; then
            PAM_FILE_PATH="$pam_file"
            if [ -f /usr/bin/authselect ]; then
                if ! authselect check; then
                    echo "
                    authselect integrity check failed. Remediation aborted!
                    This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
                    It is not recommended to manually edit the PAM files when authselect tool is available.
                    In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
                    exit 1
                fi
                CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
                if [[ ! $CURRENT_PROFILE == custom/* ]]; then
                    ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
                    authselect create-profile hardening -b $CURRENT_PROFILE
                    CURRENT_PROFILE="custom/hardening"
                    authselect apply-changes -b --backup=before-hardening-custom-profile
                    authselect select $CURRENT_PROFILE
                    for feature in $ENABLED_FEATURES; do
                        authselect enable-feature $feature
                    done
                    authselect apply-changes -b --backup=after-hardening-custom-profile
                fi
                PAM_FILE_NAME=$(basename "$pam_file")
                PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
                authselect apply-changes -b
            fi
            if grep -qP '^\s*auth\s.*\bpam_faillock.so\s.*\beven_deny_root\b' "$PAM_FILE_PATH"; then
                sed -i -E --follow-symlinks 's/(.*auth.*pam_faillock.so.*)\beven_deny_root\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
            fi
            if [ -f /usr/bin/authselect ]; then
                authselect apply-changes -b
            fi
        else
            echo "$pam_file was not found" >&2
        fi
    done
else
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth.*pam_faillock.so (preauth|authfail).*even_deny_root' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*preauth.*silent.*/ s/$/ even_deny_root/' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*authfail.*/ s/$/ even_deny_root/' "$pam_file"
        fi
    done
fi
# Set Interval For Counting Failed Password Attempts
var_accounts_passwords_pam_faillock_fail_interval='900'
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
authselect integrity check failed. Remediation aborted!
This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
It is not recommended to manually edit the PAM files when authselect tool is available.
In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    authselect enable-feature with-faillock
    authselect apply-changes -b
else
    AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth\s+required\s+pam_faillock\.so\s+(preauth silent|authfail).*$' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*sufficient.*pam_unix.so.*/i auth        required      pam_faillock.so preauth silent' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_deny.so.*/i auth        required      pam_faillock.so authfail' "$pam_file"
            sed -i --follow-symlinks '/^account.*required.*pam_unix.so.*/i account     required      pam_faillock.so' "$pam_file"
        fi
        sed -Ei 's/(auth.*)(\[default=die\])(.*pam_faillock.so)/\1required     \3/g' "$pam_file"
    done
fi
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f $FAILLOCK_CONF ]; then
    regex="^\s*fail_interval\s*="
    line="fail_interval = $var_accounts_passwords_pam_faillock_fail_interval"
    if ! grep -q $regex $FAILLOCK_CONF; then
        echo $line >>$FAILLOCK_CONF
    else
        sed -i --follow-symlinks 's|^\s*\(fail_interval\s*=\s*\)\(\S\+\)|\1'"$var_accounts_passwords_pam_faillock_fail_interval"'|g' $FAILLOCK_CONF
    fi
    for pam_file in "$${AUTH_FILES[@]}"; do
        if [ -e "$pam_file" ]; then
            PAM_FILE_PATH="$pam_file"
            if [ -f /usr/bin/authselect ]; then
                if ! authselect check; then
                    echo "
                    authselect integrity check failed. Remediation aborted!
                    This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
                    It is not recommended to manually edit the PAM files when authselect tool is available.
                    In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
                    exit 1
                fi
                CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
                if [[ ! $CURRENT_PROFILE == custom/* ]]; then
                    ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
                    authselect create-profile hardening -b $CURRENT_PROFILE
                    CURRENT_PROFILE="custom/hardening"
                    authselect apply-changes -b --backup=before-hardening-custom-profile
                    authselect select $CURRENT_PROFILE
                    for feature in $ENABLED_FEATURES; do
                        authselect enable-feature $feature
                    done
                    authselect apply-changes -b --backup=after-hardening-custom-profile
                fi
                PAM_FILE_NAME=$(basename "$pam_file")
                PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
                authselect apply-changes -b
            fi
            if grep -qP '^\s*auth\s.*\bpam_faillock.so\s.*\bfail_interval\b' "$PAM_FILE_PATH"; then
                sed -i -E --follow-symlinks 's/(.*auth.*pam_faillock.so.*)\bfail_interval\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
            fi
            if [ -f /usr/bin/authselect ]; then
                authselect apply-changes -b
            fi
        else
            echo "$pam_file was not found" >&2
        fi
    done
else
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth.*pam_faillock.so (preauth|authfail).*fail_interval' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*preauth.*silent.*/ s/$/ fail_interval='"$var_accounts_passwords_pam_faillock_fail_interval"'/' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*authfail.*/ s/$/ fail_interval='"$var_accounts_passwords_pam_faillock_fail_interval"'/' "$pam_file"
        else
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*preauth.*silent.*\)\('"fail_interval"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_fail_interval"'\3/' "$pam_file"
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*authfail.*\)\('"fail_interval"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_fail_interval"'\3/' "$pam_file"
        fi
    done
fi
# Set Lockout Time for Failed Password Attempts
var_accounts_passwords_pam_faillock_unlock_time='0'
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
authselect integrity check failed. Remediation aborted!
This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
It is not recommended to manually edit the PAM files when authselect tool is available.
In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    authselect enable-feature with-faillock

    authselect apply-changes -b
else
    AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth\s+required\s+pam_faillock\.so\s+(preauth silent|authfail).*$' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*sufficient.*pam_unix.so.*/i auth        required      pam_faillock.so preauth silent' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_deny.so.*/i auth        required      pam_faillock.so authfail' "$pam_file"
            sed -i --follow-symlinks '/^account.*required.*pam_unix.so.*/i account     required      pam_faillock.so' "$pam_file"
        fi
        sed -Ei 's/(auth.*)(\[default=die\])(.*pam_faillock.so)/\1required     \3/g' "$pam_file"
    done
fi
AUTH_FILES=("/etc/pam.d/system-auth" "/etc/pam.d/password-auth")
FAILLOCK_CONF="/etc/security/faillock.conf"
if [ -f $FAILLOCK_CONF ]; then
    regex="^\s*unlock_time\s*="
    line="unlock_time = $var_accounts_passwords_pam_faillock_unlock_time"
    if ! grep -q $regex $FAILLOCK_CONF; then
        echo $line >>$FAILLOCK_CONF
    else
        sed -i --follow-symlinks 's|^\s*\(unlock_time\s*=\s*\)\(\S\+\)|\1'"$var_accounts_passwords_pam_faillock_unlock_time"'|g' $FAILLOCK_CONF
    fi
    for pam_file in "$${AUTH_FILES[@]}"; do
        if [ -e "$pam_file" ]; then
            PAM_FILE_PATH="$pam_file"
            if [ -f /usr/bin/authselect ]; then
                if ! authselect check; then
                    echo "
                    authselect integrity check failed. Remediation aborted!
                    This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
                    It is not recommended to manually edit the PAM files when authselect tool is available.
                    In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
                    exit 1
                fi
                CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
                if [[ ! $CURRENT_PROFILE == custom/* ]]; then
                    ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
                    authselect create-profile hardening -b $CURRENT_PROFILE
                    CURRENT_PROFILE="custom/hardening"
                    authselect apply-changes -b --backup=before-hardening-custom-profile
                    authselect select $CURRENT_PROFILE
                    for feature in $ENABLED_FEATURES; do
                        authselect enable-feature $feature
                    done
                    authselect apply-changes -b --backup=after-hardening-custom-profile
                fi
                PAM_FILE_NAME=$(basename "$pam_file")
                PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
                authselect apply-changes -b
            fi
            if grep -qP '^\s*auth\s.*\bpam_faillock.so\s.*\bunlock_time\b' "$PAM_FILE_PATH"; then
                sed -i -E --follow-symlinks 's/(.*auth.*pam_faillock.so.*)\bunlock_time\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
            fi
            if [ -f /usr/bin/authselect ]; then

                authselect apply-changes -b
            fi
        else
            echo "$pam_file was not found" >&2
        fi
    done
else
    for pam_file in "$${AUTH_FILES[@]}"; do
        if ! grep -qE '^\s*auth.*pam_faillock.so (preauth|authfail).*unlock_time' "$pam_file"; then
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*preauth.*silent.*/ s/$/ unlock_time='"$var_accounts_passwords_pam_faillock_unlock_time"'/' "$pam_file"
            sed -i --follow-symlinks '/^auth.*required.*pam_faillock.so.*authfail.*/ s/$/ unlock_time='"$var_accounts_passwords_pam_faillock_unlock_time"'/' "$pam_file"
        else
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*preauth.*silent.*\)\('"unlock_time"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_unlock_time"'\3/' "$pam_file"
            sed -i --follow-symlinks 's/\(^auth.*required.*pam_faillock.so.*authfail.*\)\('"unlock_time"'=\)[0-9]\+\(.*\)/\1\2'"$var_accounts_passwords_pam_faillock_unlock_time"'\3/' "$pam_file"
        fi
    done
fi
# Ensure PAM Enforces Password Requirements - Minimum Digit Characters
var_password_pam_dcredit='-1'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^dcredit")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_dcredit"
if LC_ALL=C grep -q -m 1 -i -e "^dcredit\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^dcredit\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Prevent the Use of Dictionary Words
var_password_pam_dictcheck='1'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^dictcheck")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_dictcheck"
if LC_ALL=C grep -q -m 1 -i -e "^dictcheck\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^dictcheck\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Different Characters
var_password_pam_difok='8'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^difok")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_difok"
if LC_ALL=C grep -q -m 1 -i -e "^difok\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^difok\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Lowercase Characters
var_password_pam_lcredit='-1'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^lcredit")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_lcredit"
if LC_ALL=C grep -q -m 1 -i -e "^lcredit\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^lcredit\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Maximum Consecutive Repeating Characters from Same Character Class
var_password_pam_maxclassrepeat='4'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^maxclassrepeat")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_maxclassrepeat"
if LC_ALL=C grep -q -m 1 -i -e "^maxclassrepeat\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^maxclassrepeat\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Set Password Maximum Consecutive Repeating Characters
var_password_pam_maxrepeat='3'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^maxrepeat")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_maxrepeat"
if LC_ALL=C grep -q -m 1 -i -e "^maxrepeat\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^maxrepeat\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Different Categories
var_password_pam_minclass='4'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^minclass")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_minclass"
if LC_ALL=C grep -q -m 1 -i -e "^minclass\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^minclass\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Length
var_password_pam_minlen='15'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^minlen")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_minlen"
if LC_ALL=C grep -q -m 1 -i -e "^minlen\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^minlen\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Special Characters
var_password_pam_ocredit='-1'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^ocredit")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_ocredit"
if LC_ALL=C grep -q -m 1 -i -e "^ocredit\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^ocredit\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Authentication Retry Prompts Permitted Per-Session
var_password_pam_retry='3'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^retry")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_retry"
if LC_ALL=C grep -q -m 1 -i -e "^retry\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^retry\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Ensure PAM Enforces Password Requirements - Minimum Uppercase Characters
var_password_pam_ucredit='-1'
sed_command=('sed' '-i')
if test -L "/etc/security/pwquality.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^ucredit")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_password_pam_ucredit"
if LC_ALL=C grep -q -m 1 -i -e "^ucredit\\>" "/etc/security/pwquality.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^ucredit\\>.*/$escaped_formatted_output/gi" "/etc/security/pwquality.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/security/pwquality.conf" >> "/etc/security/pwquality.conf"
    printf '%s\n' "$formatted_output" >> "/etc/security/pwquality.conf"
fi
# Set PAM's Password Hashing Algorithm - password-auth
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
    authselect integrity check failed. Remediation aborted!
    This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
    It is not recommended to manually edit the PAM files when authselect tool is available.
    In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/password-auth")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if ! grep -qP '^\s*password\s+'"sufficient"'\s+pam_unix.so\s*.*' "$PAM_FILE_PATH"; then
    if [ "$(grep -cP '^\s*password\s+.*\s+pam_unix.so\s*' "$PAM_FILE_PATH")" -eq 1 ]; then
        sed -i -E --follow-symlinks 's/^(\s*password\s+).*(\bpam_unix.so.*)/\1'"sufficient"' \2/' "$PAM_FILE_PATH"
    else
        echo 'password    '"sufficient"'    pam_unix.so' >>"$PAM_FILE_PATH"
    fi
fi
if ! grep -qP '^\s*password\s+'"sufficient"'\s+pam_unix.so\s*.*\ssha512\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks '/\s*password\s+'"sufficient"'\s+pam_unix.so.*/ s/$/ sha512/' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
# Set PAM's Password Hashing Algorithm
PAM_FILE_PATH="/etc/pam.d/system-auth"
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
        authselect integrity check failed. Remediation aborted!
        This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
        It is not recommended to manually edit the PAM files when authselect tool is available.
        In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/system-auth")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if ! grep -qP '^\s*password\s+'"sufficient"'\s+pam_unix.so\s*.*' "$PAM_FILE_PATH"; then
    if [ "$(grep -cP '^\s*password\s+.*\s+pam_unix.so\s*' "$PAM_FILE_PATH")" -eq 1 ]; then
        sed -i -E --follow-symlinks 's/^(\s*password\s+).*(\bpam_unix.so.*)/\1'"sufficient"' \2/' "$PAM_FILE_PATH"
    else
        echo 'password    '"sufficient"'    pam_unix.so' >>"$PAM_FILE_PATH"
    fi
fi
if ! grep -qP '^\s*password\s+'"sufficient"'\s+pam_unix.so\s*.*\ssha512\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks '/\s*password\s+'"sufficient"'\s+pam_unix.so.*/ s/$/ sha512/' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
# Ensure PAM Displays Last Logon/Access Notification
PAM_FILE_PATH="/etc/pam.d/postlogin"
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
        authselect integrity check failed. Remediation aborted!
        This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
        It is not recommended to manually edit the PAM files when authselect tool is available.
        In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/postlogin")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if ! grep -qP '^\s*session\s+'"required"'\s+pam_lastlog.so\s*.*' "$PAM_FILE_PATH"; then
    if [ "$(grep -cP '^\s*session\s+.*\s+pam_lastlog.so\s*' "$PAM_FILE_PATH")" -eq 1 ]; then
        sed -i -E --follow-symlinks 's/^(\s*session\s+).*(\bpam_lastlog.so.*)/\1'"required"' \2/' "$PAM_FILE_PATH"
    else
        sed -i --follow-symlinks '1i session     '"required"'    pam_lastlog.so' "$PAM_FILE_PATH"
    fi
fi
if ! grep -qP '^\s*session\s+'"required"'\s+pam_lastlog.so\s*.*\sshowfailed\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks '/\s*session\s+'"required"'\s+pam_lastlog.so.*/ s/$/ showfailed/' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
PAM_FILE_PATH="/etc/pam.d/postlogin"
if [ -f /usr/bin/authselect ]; then
    if ! authselect check; then
        echo "
            authselect integrity check failed. Remediation aborted!
            This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
            It is not recommended to manually edit the PAM files when authselect tool is available.
            In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
    fi
    CURRENT_PROFILE=$(authselect current -r | awk '{ print $1 }')
    if [[ ! $CURRENT_PROFILE == custom/* ]]; then
        ENABLED_FEATURES=$(authselect current | tail -n+3 | awk '{ print $2 }')
        authselect create-profile hardening -b $CURRENT_PROFILE
        CURRENT_PROFILE="custom/hardening"
        authselect apply-changes -b --backup=before-hardening-custom-profile
        authselect select $CURRENT_PROFILE
        for feature in $ENABLED_FEATURES; do
            authselect enable-feature $feature
        done
        authselect apply-changes -b --backup=after-hardening-custom-profile
    fi
    PAM_FILE_NAME=$(basename "/etc/pam.d/postlogin")
    PAM_FILE_PATH="/etc/authselect/$CURRENT_PROFILE/$PAM_FILE_NAME"
    authselect apply-changes -b
fi
if grep -qP '^\s*session\s.*\bpam_lastlog.so\s.*\bsilent\b' "$PAM_FILE_PATH"; then
    sed -i -E --follow-symlinks 's/(.*session.*pam_lastlog.so.*)\bsilent\b=?[[:alnum:]]*(.*)/\1\2/g' "$PAM_FILE_PATH"
fi
if [ -f /usr/bin/authselect ]; then
    authselect apply-changes -b
fi
## Protect Physical Console Access
# Support session locking with tmux
if ! grep -x '  case "$name" in sshd|login) tmux ;; esac' /etc/bashrc /etc/profile.d/*.sh; then
    cat >> /etc/profile.d/tmux.sh <<'EOF'
if [ "$PS1" ]; then
  parent=$(ps -o ppid= -p $$)
  name=$(ps -o comm= -p $parent)
  case "$name" in sshd|login) tmux ;; esac
fi
EOF
    chmod 0644 /etc/profile.d/tmux.sh
fi
# Configure tmux to lock session after inactivity
tmux_conf="/etc/tmux.conf"
touch "$${tmux_conf}"
if grep -qP '^\s*set\s+-g\s+lock-after-time' "$tmux_conf" ; then
    sed -i 's/^\s*set\s\+-g\s\+lock-after-time.*$/set -g lock-after-time 900/' "$tmux_conf"
else
    echo "set -g lock-after-time 900" >> "$tmux_conf"
fi
chmod 0644 "$tmux_conf"
# Configure the tmux Lock Command
tmux_conf="/etc/tmux.conf"
touch "$${tmux_conf}"
if grep -qP '^\s*set\s+-g\s+lock-command' "$tmux_conf" ; then
    sed -i 's/^\s*set\s\+-g\s\+lock-command.*$/set -g lock-command vlock/' "$tmux_conf"
else
    echo "set -g lock-command vlock" >> "$tmux_conf"
fi
chmod 0644 "$tmux_conf"
# Configure the tmux lock session key binding
tmux_conf="/etc/tmux.conf"
if grep -qP '^\s*bind\s+\w\s+lock-session' "$tmux_conf" ; then
    sed -i 's/\s*bind\s\+\w\s\+lock-session.*$/bind X lock-session/' "$tmux_conf"
else
    echo "bind X lock-session" >> "$tmux_conf"
fi
chmod 0644 "$tmux_conf"
# Prevent user from disabling the screen lock
if grep -q 'tmux\s*$' /etc/shells ; then
	sed -i '/tmux\s*$/d' /etc/shells
fi
# Disable debug-shell SystemD Service
systemctl disable --now debug-shell.service
systemctl mask --now debug-shell.service
# Disable Ctrl-Alt-Del Burst Action
echo "CtrlAltDelBurstAction=none" >> /etc/systemd/system.conf
# Disable Ctrl-Alt-Del Reboot Activation
systemctl disable --now ctrl-alt-del.target
systemctl mask --now ctrl-alt-del.target
## Protect Accounts by Restricting Password-Based Login
# Set Account Expiration Following Inactivity
var_account_disable_post_pw_expiration='35'
if grep -qP '^INACTIVE=-1$' "/etc/default/useradd"; then
    sed -i -E "s/^(INACTIVE=).*$/\135/" /etc/default/useradd
fi
# Set Password Maximum Age
var_accounts_maximum_age_login_defs='60'
grep -q ^PASS_MAX_DAYS /etc/login.defs && \
  sed -i "s/PASS_MAX_DAYS.*/PASS_MAX_DAYS     $var_accounts_maximum_age_login_defs/g" /etc/login.defs
if ! [ $? -eq 0 ]; then
    echo "PASS_MAX_DAYS      $var_accounts_maximum_age_login_defs" >> /etc/login.defs
fi
# Set Password Minimum Age
var_accounts_minimum_age_login_defs='1'
grep -q ^PASS_MIN_DAYS /etc/login.defs && \
  sed -i "s/PASS_MIN_DAYS.*/PASS_MIN_DAYS     $var_accounts_minimum_age_login_defs/g" /etc/login.defs
if ! [ $? -eq 0 ]; then
    echo "PASS_MIN_DAYS      $var_accounts_minimum_age_login_defs" >> /etc/login.defs
fi
# Set Existing Passwords Maximum Age
for username in $(cut -d: -f1 /etc/passwd); do
  chage -M 60 "$username"
done
# Set Existing Passwords Minimum Age
for username in $(cut -d: -f1 /etc/passwd); do
  chage -m 1 "$username"
done
## Secure Session Configuration Files for Login Accounts
# Ensure the Default Bash Umask is Set Correctly
var_accounts_user_umask='077'
grep -q "^\s*umask" /etc/bashrc && \
  sed -i -E -e "s/^(\s*umask).*/\1 $var_accounts_user_umask/g" /etc/bashrc
if ! [ $? -eq 0 ]; then
    echo "umask $var_accounts_user_umask" >> /etc/bashrc
fi
# Ensure the Default C Shell Umask is Set Correctly
var_accounts_user_umask='077'
grep -q "^\s*umask" /etc/csh.cshrc && \
  sed -i -E -e "s/^(\s*umask).*/\1 $var_accounts_user_umask/g" /etc/csh.cshrc
if ! [ $? -eq 0 ]; then
    echo "umask $var_accounts_user_umask" >> /etc/csh.cshrc
fi
# Ensure the Default Umask is Set Correctly in login.defs
var_accounts_user_umask='077'
sed_command=('sed' '-i')
if test -L "/etc/login.defs"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^UMASK")
printf -v formatted_output "%s %s" "$stripped_key" "$var_accounts_user_umask"
if LC_ALL=C grep -q -m 1 -i -e "^UMASK\\>" "/etc/login.defs"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^UMASK\\>.*/$escaped_formatted_output/gi" "/etc/login.defs"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/login.defs" >> "/etc/login.defs"
    printf '%s\n' "$formatted_output" >> "/etc/login.defs"
fi
# Ensure the Default Umask is Set Correctly in /etc/profile
var_accounts_user_umask='077'
grep -qE '^[^#]*umask' /etc/profile && \
  sed -i "s/umask.*/umask $var_accounts_user_umask/g" /etc/profile
if ! [ $? -eq 0 ]; then
    echo "umask $var_accounts_user_umask" >> /etc/profile
fi
# Ensure the Logon Failure Delay is Set Correctly in login.defs
var_accounts_fail_delay='4'
sed_command=('sed' '-i')
if test -L "/etc/login.defs"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^FAIL_DELAY")
printf -v formatted_output "%s %s" "$stripped_key" "$var_accounts_fail_delay"
if LC_ALL=C grep -q -m 1 -i -e "^FAIL_DELAY\\>" "/etc/login.defs"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^FAIL_DELAY\\>.*/$escaped_formatted_output/gi" "/etc/login.defs"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/login.defs" >> "/etc/login.defs"
    printf '%s\n' "$formatted_output" >> "/etc/login.defs"
fi
# Limit the Number of Concurrent Login Sessions Allowed Per User
var_accounts_max_concurrent_login_sessions='10'
if grep -q '^[^#]*\<maxlogins\>' /etc/security/limits.d/*.conf; then
	sed -i "/^[^#]*\<maxlogins\>/ s/maxlogins.*/maxlogins $var_accounts_max_concurrent_login_sessions/" /etc/security/limits.d/*.conf
elif grep -q '^[^#]*\<maxlogins\>' /etc/security/limits.conf; then
	sed -i "/^[^#]*\<maxlogins\>/ s/maxlogins.*/maxlogins $var_accounts_max_concurrent_login_sessions/" /etc/security/limits.conf
else
	echo "*	hard	maxlogins	$var_accounts_max_concurrent_login_sessions" >> /etc/security/limits.conf
fi
### System Accounting with auditd
## Configure auditd Rules for Comprehensive Auditing
# Record Events that Modify the System's Discretionary Access Controls
## Configure auditd Data Retention
# Configure auditd Disk Error Action on Disk Error
var_auditd_disk_error_action='syslog|single|halt'
var_auditd_disk_error_action="$(echo $var_auditd_disk_error_action | cut -d \| -f 1)"
sed_command=('sed' '-i')
if test -L "/etc/audit/auditd.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^disk_error_action")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_auditd_disk_error_action"
if LC_ALL=C grep -q -m 1 -i -e "^disk_error_action\\>" "/etc/audit/auditd.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^disk_error_action\\>.*/$escaped_formatted_output/gi" "/etc/audit/auditd.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/audit/auditd.conf" >> "/etc/audit/auditd.conf"
    printf '%s\n' "$formatted_output" >> "/etc/audit/auditd.conf"
fi
# Configure auditd Disk Full Action when Disk Space Is Full
var_auditd_disk_full_action='syslog|single|halt'
var_auditd_disk_full_action="$(echo $var_auditd_disk_full_action | cut -d \| -f 1)"
sed_command=('sed' '-i')
if test -L "/etc/audit/auditd.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^disk_full_action")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_auditd_disk_full_action"
if LC_ALL=C grep -q -m 1 -i -e "^disk_full_action\\>" "/etc/audit/auditd.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^disk_full_action\\>.*/$escaped_formatted_output/gi" "/etc/audit/auditd.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/audit/auditd.conf" >> "/etc/audit/auditd.conf"
    printf '%s\n' "$formatted_output" >> "/etc/audit/auditd.conf"
fi
# Configure auditd space_left Action on Low Disk Space
var_auditd_space_left_action='email'
AUDITCONFIG=/etc/audit/auditd.conf
sed_command=('sed' '-i')
if test -L "$AUDITCONFIG"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^space_left_action")
printf -v formatted_output "%s = %s" "$stripped_key" "$var_auditd_space_left_action"
if LC_ALL=C grep -q -m 1 -i -e "^space_left_action\\>" "$AUDITCONFIG"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^space_left_action\\>.*/$escaped_formatted_output/gi" "$AUDITCONFIG"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "$AUDITCONFIG" >> "$AUDITCONFIG"
    printf '%s\n' "$formatted_output" >> "$AUDITCONFIG"
fi
# Remediation is applicable only in certain platforms
var_auditd_space_left_percentage='25'
grep -q "^space_left[[:space:]]*=.*$" /etc/audit/auditd.conf && \
  sed -i "s/^space_left[[:space:]]*=.*$/space_left = $var_auditd_space_left_percentage%/g" /etc/audit/auditd.conf || \
  echo "space_left = $var_auditd_space_left_percentage%" >> /etc/audit/auditd.conf
# Set hostname as computer node name in audit logs
if [ -e "/etc/audit/auditd.conf" ] ; then
    LC_ALL=C sed -i "/^\s*name_format\s*=\s*/Id" "/etc/audit/auditd.conf"
else
    touch "/etc/audit/auditd.conf"
fi
cp "/etc/audit/auditd.conf" "/etc/audit/auditd.conf.bak"
printf '%s\n' "name_format = hostname" >> "/etc/audit/auditd.conf"
rm "/etc/audit/auditd.conf.bak"
## System Accounting with auditd
# Configure immutable Audit login UIDs
cat << 'EOF' > /etc/audit/rules.d/11-loginuid.rules
## Make the loginuid immutable. This prevents tampering with the auid.
--loginuid-immutable

EOF
chmod o-rwx /etc/audit/rules.d/11-loginuid.rules
augenrules --load
### GRUB2 bootloader configuration
## UEFI GRUB2 bootloader configuration
# Set the UEFI Boot Loader Admin Username to a Non-Default Value
sed -i 's/set superusers="root"/set superusers="admin"/' /etc/grub.d/01_users
### Configure Syslog
## Ensure Proper Configuration of Log Files
# Ensure Rsyslog Authenticates Off-Loaded Audit Records	
sed -i '/^.*\$ActionSendStreamDriverAuthMode.*/d' /etc/rsyslog.conf /etc/rsyslog.d/*.conf 2> /dev/null
if [ -e "/etc/rsyslog.d/stream_driver_auth.conf" ] ; then
    LC_ALL=C sed -i "/^\s*\$ActionSendStreamDriverAuthMode /Id" "/etc/rsyslog.d/stream_driver_auth.conf"
else
    touch "/etc/rsyslog.d/stream_driver_auth.conf"
fi
cp "/etc/rsyslog.d/stream_driver_auth.conf" "/etc/rsyslog.d/stream_driver_auth.conf.bak"
printf '%s\n' "\$ActionSendStreamDriverAuthMode x509/name" >> "/etc/rsyslog.d/stream_driver_auth.conf"
rm "/etc/rsyslog.d/stream_driver_auth.conf.bak"
# Ensure Rsyslog Encrypts Off-Loaded Audit Records	
if [ -e "/etc/rsyslog.d/encrypt.conf" ] ; then
    LC_ALL=C sed -i "/^\s*\$ActionSendStreamDriverMode /Id" "/etc/rsyslog.d/encrypt.conf"
else
    touch "/etc/rsyslog.d/encrypt.conf"
fi
cp "/etc/rsyslog.d/encrypt.conf" "/etc/rsyslog.d/encrypt.conf.bak"
printf '%s\n' "\$ActionSendStreamDriverMode 1" >> "/etc/rsyslog.d/encrypt.conf"
rm "/etc/rsyslog.d/encrypt.conf.bak"
# Ensure Rsyslog Encrypts Off-Loaded Audit Records
if [ -e "/etc/rsyslog.d/encrypt.conf" ] ; then
    LC_ALL=C sed -i "/^\s*\$DefaultNetstreamDriver /Id" "/etc/rsyslog.d/encrypt.conf"
else
    touch "/etc/rsyslog.d/encrypt.conf"
fi
cp "/etc/rsyslog.d/encrypt.conf" "/etc/rsyslog.d/encrypt.conf.bak"
printf '%s\n' "\$DefaultNetstreamDriver gtls" >> "/etc/rsyslog.d/encrypt.conf"
rm "/etc/rsyslog.d/encrypt.conf.bak"
# Ensure remote access methods are monitored in Rsyslog
declare -A REMOTE_METHODS=( ['auth.*']='^.*auth\.\*.*$' ['authpriv.*']='^.*authpriv\.\*.*$' ['daemon.*']='^.*daemon\.\*.*$' )
if [[ ! -f /etc/rsyslog.conf ]]; then
	touch /etc/rsyslog.conf
fi
APPEND_LINE=$(sed -rn '/^\S+\s+\/var\/log\/secure$/p' /etc/rsyslog.conf)
for K in "$${!REMOTE_METHODS[@]}"
do
	if ! grep -rq "$${REMOTE_METHODS[$K]}" /etc/rsyslog.*; then
		if [[ ! -z $${APPEND_LINE} ]]; then
			sed -r -i "0,/^(\S+\s+\/var\/log\/secure$)/s//\1\n$${K} \/var\/log\/secure/" /etc/rsyslog.conf
		else
			echo "$${K} \/var\/log\/secure/" >> /etc/rsyslog.conf
		fi
	fi
done
## Rsyslog Logs Sent To Remote Host
# Ensure Logs Sent To Remote Host
rsyslog_remote_loghost_address='logcollector'
sed_command=('sed' '-i')
if test -L "/etc/rsyslog.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^\*\.\*")
printf -v formatted_output "%s %s" "$stripped_key" "@@$rsyslog_remote_loghost_address"
if LC_ALL=C grep -q -m 1 -i -e "^\*\.\*\\>" "/etc/rsyslog.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^\*\.\*\\>.*/$escaped_formatted_output/gi" "/etc/rsyslog.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/rsyslog.conf" >> "/etc/rsyslog.conf"
    printf '%s\n' "$formatted_output" >> "/etc/rsyslog.conf"
fi
### Network Configuration and Firewalls
## firewalld
# Configure the Firewalld Ports
## IPv6
# Configure Accepting Router Advertisements on All IPv6 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.all.accept_ra.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_all_accept_ra_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.all.accept_ra="$sysctl_net_ipv6_conf_all_accept_ra_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.all.accept_ra")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_all_accept_ra_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.all.accept_ra\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.all.accept_ra\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Accepting ICMP Redirects for All IPv6 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.all.accept_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_all_accept_redirects_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.all.accept_redirects="$sysctl_net_ipv6_conf_all_accept_redirects_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.all.accept_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_all_accept_redirects_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.all.accept_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.all.accept_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting Source-Routed Packets on all IPv6 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.all.accept_source_route.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_all_accept_source_route_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.all.accept_source_route="$sysctl_net_ipv6_conf_all_accept_source_route_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.all.accept_source_route")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_all_accept_source_route_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.all.accept_source_route\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.all.accept_source_route\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for IPv6 Forwarding
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.all.forwarding.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_all_forwarding_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.all.forwarding="$sysctl_net_ipv6_conf_all_forwarding_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.all.forwarding")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_all_forwarding_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.all.forwarding\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.all.forwarding\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Accepting Router Advertisements on all IPv6 Interfaces by Default
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.default.accept_ra.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_default_accept_ra_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.default.accept_ra="$sysctl_net_ipv6_conf_default_accept_ra_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.default.accept_ra")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_default_accept_ra_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.default.accept_ra\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.default.accept_ra\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting ICMP Redirects by Default on IPv6 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.default.accept_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_default_accept_redirects_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.default.accept_redirects="$sysctl_net_ipv6_conf_default_accept_redirects_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.default.accept_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_default_accept_redirects_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.default.accept_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.default.accept_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting Source-Routed Packets on IPv6 Interfaces by Default
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv6.conf.default.accept_source_route.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv6_conf_default_accept_source_route_value='0'
/sbin/sysctl -q -n -w net.ipv6.conf.default.accept_source_route="$sysctl_net_ipv6_conf_default_accept_source_route_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv6.conf.default.accept_source_route")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv6_conf_default_accept_source_route_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv6.conf.default.accept_source_route\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv6.conf.default.accept_source_route\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
## Kernel Parameters Which Affect Networking
# Disable Accepting ICMP Redirects for All IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.all.accept_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_all_accept_redirects_value='0'
/sbin/sysctl -q -n -w net.ipv4.conf.all.accept_redirects="$sysctl_net_ipv4_conf_all_accept_redirects_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.all.accept_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_all_accept_redirects_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.all.accept_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.all.accept_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting Source-Routed Packets on all IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.all.accept_source_route.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_all_accept_source_route_value='0'
/sbin/sysctl -q -n -w net.ipv4.conf.all.accept_source_route="$sysctl_net_ipv4_conf_all_accept_source_route_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.all.accept_source_route")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_all_accept_source_route_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.all.accept_source_route\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.all.accept_source_route\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for IPv4 Forwarding on all IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.all.forwarding.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_all_forwarding_value='0'
/sbin/sysctl -q -n -w net.ipv4.conf.all.forwarding="$sysctl_net_ipv4_conf_all_forwarding_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.all.forwarding")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_all_forwarding_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.all.forwarding\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.all.forwarding\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Enable Kernel Parameter to Use Reverse Path Filtering on all IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.all.rp_filter.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_all_rp_filter_value='1'
/sbin/sysctl -q -n -w net.ipv4.conf.all.rp_filter="$sysctl_net_ipv4_conf_all_rp_filter_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.all.rp_filter")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_all_rp_filter_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.all.rp_filter\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.all.rp_filter\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting ICMP Redirects by Default on IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.default.accept_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_default_accept_redirects_value='0'
/sbin/sysctl -q -n -w net.ipv4.conf.default.accept_redirects="$sysctl_net_ipv4_conf_default_accept_redirects_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.default.accept_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_default_accept_redirects_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.default.accept_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.default.accept_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Accepting Source-Routed Packets on IPv4 Interfaces by Default
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.default.accept_source_route.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_conf_default_accept_source_route_value='0'
/sbin/sysctl -q -n -w net.ipv4.conf.default.accept_source_route="$sysctl_net_ipv4_conf_default_accept_source_route_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.default.accept_source_route")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_conf_default_accept_source_route_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.default.accept_source_route\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.default.accept_source_route\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Enable Kernel Parameter to Ignore ICMP Broadcast Echo Requests on IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.icmp_echo_ignore_broadcasts.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_net_ipv4_icmp_echo_ignore_broadcasts_value='1'
/sbin/sysctl -q -n -w net.ipv4.icmp_echo_ignore_broadcasts="$sysctl_net_ipv4_icmp_echo_ignore_broadcasts_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.icmp_echo_ignore_broadcasts")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_net_ipv4_icmp_echo_ignore_broadcasts_value"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.icmp_echo_ignore_broadcasts\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.icmp_echo_ignore_broadcasts\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Sending ICMP Redirects on all IPv4 Interfaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.all.send_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w net.ipv4.conf.all.send_redirects="0"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.all.send_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "0"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.all.send_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.all.send_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Parameter for Sending ICMP Redirects on all IPv4 Interfaces by Default
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.ipv4.conf.default.send_redirects.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w net.ipv4.conf.default.send_redirects="0"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.ipv4.conf.default.send_redirects")
printf -v formatted_output "%s = %s" "$stripped_key" "0"
if LC_ALL=C grep -q -m 1 -i -e "^net.ipv4.conf.default.send_redirects\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.ipv4.conf.default.send_redirects\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
## Uncommon Network Protocols
# Disable ATM Support
if LC_ALL=C grep -q -m 1 "^install atm" /etc/modprobe.d/atm.conf ; then	
	sed -i 's#^install atm.*#install atm /bin/true#g' /etc/modprobe.d/atm.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/atm.conf
	echo "install atm /bin/true" >> /etc/modprobe.d/atm.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist atm$" /etc/modprobe.d/atm.conf ; then
	echo "blacklist atm" >> /etc/modprobe.d/atm.conf
fi
# Disable CAN Support
if LC_ALL=C grep -q -m 1 "^install can" /etc/modprobe.d/can.conf ; then
	sed -i 's#^install can.*#install can /bin/true#g' /etc/modprobe.d/can.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/can.conf
	echo "install can /bin/true" >> /etc/modprobe.d/can.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist can$" /etc/modprobe.d/can.conf ; then
	echo "blacklist can" >> /etc/modprobe.d/can.conf
fi
# Disable IEEE 1394 (FireWire) Support
if LC_ALL=C grep -q -m 1 "^install firewire-core" /etc/modprobe.d/firewire-core.conf ; then
	sed -i 's#^install firewire-core.*#install firewire-core /bin/true#g' /etc/modprobe.d/firewire-core.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/firewire-core.conf
	echo "install firewire-core /bin/true" >> /etc/modprobe.d/firewire-core.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist firewire-core$" /etc/modprobe.d/firewire-core.conf ; then
	echo "blacklist firewire-core" >> /etc/modprobe.d/firewire-core.conf
fi
# Disable SCTP Support
if LC_ALL=C grep -q -m 1 "^install sctp" /etc/modprobe.d/sctp.conf ; then
	sed -i 's#^install sctp.*#install sctp /bin/true#g' /etc/modprobe.d/sctp.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/sctp.conf
	echo "install sctp /bin/true" >> /etc/modprobe.d/sctp.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist sctp$" /etc/modprobe.d/sctp.conf ; then
	echo "blacklist sctp" >> /etc/modprobe.d/sctp.conf
fi
# Disable TIPC Support
if LC_ALL=C grep -q -m 1 "^install tipc" /etc/modprobe.d/tipc.conf ; then
	sed -i 's#^install tipc.*#install tipc /bin/true#g' /etc/modprobe.d/tipc.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/tipc.conf
	echo "install tipc /bin/true" >> /etc/modprobe.d/tipc.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist tipc$" /etc/modprobe.d/tipc.conf ; then
	echo "blacklist tipc" >> /etc/modprobe.d/tipc.conf
fi
## Wireless Networking
# Disable Bluetooth Kernel Module
if LC_ALL=C grep -q -m 1 "^install bluetooth" /etc/modprobe.d/bluetooth.conf ; then
	sed -i 's#^install bluetooth.*#install bluetooth /bin/true#g' /etc/modprobe.d/bluetooth.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/bluetooth.conf
	echo "install bluetooth /bin/true" >> /etc/modprobe.d/bluetooth.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist bluetooth$" /etc/modprobe.d/bluetooth.conf ; then
	echo "blacklist bluetooth" >> /etc/modprobe.d/bluetooth.conf
fi
# Configure Multiple DNS Servers in /etc/resolv.conf
### File Permissions and Masks
## Verify Permissions on Important Files and Directories
# Verify Permissions on /etc/audit/rules.d/*.rules
find -H /etc/audit/rules.d/ -maxdepth 1 -perm /u+xs,g+xws,o+xwrt -type f -regex '^.*rules$' -exec chmod u-xs,g-xws,o-xwrt {} \;
# Enable Kernel Parameter to Enforce DAC on Hardlinks
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*fs.protected_hardlinks.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w fs.protected_hardlinks="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^fs.protected_hardlinks")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^fs.protected_hardlinks\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^fs.protected_hardlinks\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Enable Kernel Parameter to Enforce DAC on Symlinks
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*fs.protected_symlinks.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w fs.protected_symlinks="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^fs.protected_symlinks")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^fs.protected_symlinks\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^fs.protected_symlinks\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
## Restrict Dynamic Mounting and Unmounting of Filesystems
# Disable Mounting of cramfs
if LC_ALL=C grep -q -m 1 "^install cramfs" /etc/modprobe.d/cramfs.conf ; then
	sed -i 's#^install cramfs.*#install cramfs /bin/true#g' /etc/modprobe.d/cramfs.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/cramfs.conf
	echo "install cramfs /bin/true" >> /etc/modprobe.d/cramfs.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist cramfs$" /etc/modprobe.d/cramfs.conf ; then
	echo "blacklist cramfs" >> /etc/modprobe.d/cramfs.conf
fi
# Disable Modprobe Loading of USB Storage Driver
if LC_ALL=C grep -q -m 1 "^install usb-storage" /etc/modprobe.d/usb-storage.conf ; then
	sed -i 's#^install usb-storage.*#install usb-storage /bin/true#g' /etc/modprobe.d/usb-storage.conf
else
	echo -e "\n# Disable per security requirements" >> /etc/modprobe.d/usb-storage.conf
	echo "install usb-storage /bin/true" >> /etc/modprobe.d/usb-storage.conf
fi
if ! LC_ALL=C grep -q -m 1 "^blacklist usb-storage$" /etc/modprobe.d/usb-storage.conf ; then
	echo "blacklist usb-storage" >> /etc/modprobe.d/usb-storage.conf
fi
## Restrict Partition Mount Options
# Add nosuid Option to /boot
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/boot")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/boot' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /boot in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /boot)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /boot  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/boot"; then
    if mountpoint -q "/boot"; then
        mount -o remount --target "/boot"
    else
        mount --target "/boot"
    fi
fi
# Add nosuid Option to /boot/efi
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/boot/efi")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/boot/efi' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /boot/efi in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /boot/efi)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /boot/efi  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/boot/efi"; then
    if mountpoint -q "/boot/efi"; then
        mount -o remount --target "/boot/efi"
    else
        mount --target "/boot/efi"
    fi
fi
# Add nodev Option to /dev/shm
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /dev/shm)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nodev)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo "tmpfs /dev/shm tmpfs defaults,$${previous_mount_opts}nodev 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nodev")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nodev|" /etc/fstab
fi
if mkdir -p "/dev/shm"; then
    if mountpoint -q "/dev/shm"; then
        mount -o remount --target "/dev/shm"
    else
        mount --target "/dev/shm"
    fi
fi
# Add noexec Option to /dev/shm
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /dev/shm)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo "tmpfs /dev/shm tmpfs defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi
if mkdir -p "/dev/shm"; then
    if mountpoint -q "/dev/shm"; then
        mount -o remount --target "/dev/shm"
    else
        mount --target "/dev/shm"
    fi
fi
# Add nosuid Option to /dev/shm
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /dev/shm)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo "tmpfs /dev/shm tmpfs defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/dev/shm"; then
    if mountpoint -q "/dev/shm"; then
        mount -o remount --target "/dev/shm"
    else
        mount --target "/dev/shm"
    fi
fi
# Add noexec Option to /home
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/home")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/home' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /home in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /home)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /home  defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi

if mkdir -p "/home"; then
    if mountpoint -q "/home"; then
        mount -o remount --target "/home"
    else
        mount --target "/home"
    fi
fi
# Add nosuid Option to /home
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/home")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/home' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /home in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /home)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /home  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/home"; then
    if mountpoint -q "/home"; then
        mount -o remount --target "/home"
    else
        mount --target "/home"
    fi
fi
# Add nodev Option to /tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nodev)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /tmp  defaults,$${previous_mount_opts}nodev 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nodev")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nodev|" /etc/fstab
fi
if mkdir -p "/tmp"; then
    if mountpoint -q "/tmp"; then
        mount -o remount --target "/tmp"
    else
        mount --target "/tmp"
    fi
fi
# Add noexec Option to /tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /tmp  defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi
if mkdir -p "/tmp"; then
    if mountpoint -q "/tmp"; then
        mount -o remount --target "/tmp"
    else
        mount --target "/tmp"
    fi
fi
# Add nosuid Option to /tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /tmp  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/tmp"; then
    if mountpoint -q "/tmp"; then
        mount -o remount --target "/tmp"
    else
        mount --target "/tmp"
    fi
fi
# Add nodev Option to /var/log/audit
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log/audit")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log/audit' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log/audit in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log/audit)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nodev)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log/audit  defaults,$${previous_mount_opts}nodev 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nodev")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nodev|" /etc/fstab
fi
if mkdir -p "/var/log/audit"; then
    if mountpoint -q "/var/log/audit"; then
        mount -o remount --target "/var/log/audit"
    else
        mount --target "/var/log/audit"
    fi
fi
# Add noexec Option to /var/log/audit
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log/audit")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log/audit' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log/audit in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log/audit)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log/audit  defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi
if mkdir -p "/var/log/audit"; then
    if mountpoint -q "/var/log/audit"; then
        mount -o remount --target "/var/log/audit"
    else
        mount --target "/var/log/audit"
    fi
fi
# Add nosuid Option to /var/log/audit
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log/audit")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log/audit' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log/audit in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log/audit)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log/audit  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/var/log/audit"; then
    if mountpoint -q "/var/log/audit"; then
        mount -o remount --target "/var/log/audit"
    else
        mount --target "/var/log/audit"
    fi
fi
# Add nodev Option to /var/log
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nodev)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log  defaults,$${previous_mount_opts}nodev 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nodev")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nodev|" /etc/fstab
fi
if mkdir -p "/var/log"; then
    if mountpoint -q "/var/log"; then
        mount -o remount --target "/var/log"
    else
        mount --target "/var/log"
    fi
fi
# Add noexec Option to /var/log
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log  defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi
if mkdir -p "/var/log"; then
    if mountpoint -q "/var/log"; then
        mount -o remount --target "/var/log"
    else
        mount --target "/var/log"
    fi
fi
# Add nosuid Option to /var/log
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/log")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/log' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/log in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/log)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/log  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/var/log"; then
    if mountpoint -q "/var/log"; then
        mount -o remount --target "/var/log"
    else
        mount --target "/var/log"
    fi
fi
# Add nodev Option to /var/tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nodev)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/tmp  defaults,$${previous_mount_opts}nodev 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nodev")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nodev|" /etc/fstab
fi
if mkdir -p "/var/tmp"; then
    if mountpoint -q "/var/tmp"; then
        mount -o remount --target "/var/tmp"
    else
        mount --target "/var/tmp"
    fi
fi
# Add noexec Option to /var/tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|noexec)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/tmp  defaults,$${previous_mount_opts}noexec 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "noexec")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,noexec|" /etc/fstab
fi
if mkdir -p "/var/tmp"; then
    if mountpoint -q "/var/tmp"; then
        mount -o remount --target "/var/tmp"
    else
        mount --target "/var/tmp"
    fi
fi
# Add nosuid Option to /var/tmp
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" "/var/tmp")"
grep "$mount_point_match_regexp" -q /etc/fstab ||
    {
        echo "The mount point '/var/tmp' is not even in /etc/fstab, so we can't set up mount options" >&2
        echo "Not remediating, because there is no record of /var/tmp in /etc/fstab" >&2
        return 1
    }
mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" /var/tmp)"
if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
        sed -E "s/(rw|defaults|seclabel|nosuid)(,|$)//g;s/,$//")
    [ "$previous_mount_opts" ] && previous_mount_opts+=","
    echo " /var/tmp  defaults,$${previous_mount_opts}nosuid 0 0" >>/etc/fstab
elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "nosuid")" -eq 0 ]; then
    previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
    sed -i "s|\($${mount_point_match_regexp}.*$${previous_mount_opts}\)|\1,nosuid|" /etc/fstab
fi
if mkdir -p "/var/tmp"; then
    if mountpoint -q "/var/tmp"; then
        mount -o remount --target "/var/tmp"
    else
        mount --target "/var/tmp"
    fi
fi
## Restrict Programs from Dangerous Execution Patterns
# Disable acquiring, saving, and processing core dumps
SYSTEMCTL_EXEC='/usr/bin/systemctl'
"$SYSTEMCTL_EXEC" stop 'systemd-coredump.service'
"$SYSTEMCTL_EXEC" disable 'systemd-coredump.service'
"$SYSTEMCTL_EXEC" mask 'systemd-coredump.service'
if "$SYSTEMCTL_EXEC" list-unit-files | grep -q '^systemd-coredump.socket'; then
    "$SYSTEMCTL_EXEC" stop 'systemd-coredump.socket'
    "$SYSTEMCTL_EXEC" mask 'systemd-coredump.socket'
fi
"$SYSTEMCTL_EXEC" reset-failed 'systemd-coredump.service' || true
# Disable core dump backtraces
if [ -e "/etc/systemd/coredump.conf" ] ; then
    LC_ALL=C sed -i "/^\s*ProcessSizeMax\s*=\s*/Id" "/etc/systemd/coredump.conf"
else
    touch "/etc/systemd/coredump.conf"
fi
cp "/etc/systemd/coredump.conf" "/etc/systemd/coredump.conf.bak"
printf '%s\n' "ProcessSizeMax=0" >> "/etc/systemd/coredump.conf"
rm "/etc/systemd/coredump.conf.bak"
# Disable storing core dump
if [ -e "/etc/systemd/coredump.conf" ] ; then
    LC_ALL=C sed -i "/^\s*Storage\s*=\s*/Id" "/etc/systemd/coredump.conf"
else
    touch "/etc/systemd/coredump.conf"
fi
cp "/etc/systemd/coredump.conf" "/etc/systemd/coredump.conf.bak"
printf '%s\n' "Storage=none" >> "/etc/systemd/coredump.conf"
rm "/etc/systemd/coredump.conf.bak"
# Disable Core Dumps for All Users
SECURITY_LIMITS_FILE="/etc/security/limits.conf"
if grep -qE '^\s*\*\s+hard\s+core' $SECURITY_LIMITS_FILE; then
        sed -ri 's/(hard\s+core\s+)[[:digit:]]+/\1 0/' $SECURITY_LIMITS_FILE
else
        echo "*     hard   core    0" >> $SECURITY_LIMITS_FILE
fi
if ls /etc/security/limits.d/*.conf > /dev/null; then
        sed -ri '/^\s*\*\s+hard\s+core/d' /etc/security/limits.d/*.conf
fi
# Restrict Exposed Kernel Pointer Addresses Access
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.kptr_restrict.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
sysctl_kernel_kptr_restrict_value='1'
/sbin/sysctl -q -n -w kernel.kptr_restrict="$sysctl_kernel_kptr_restrict_value"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.kptr_restrict")
printf -v formatted_output "%s = %s" "$stripped_key" "$sysctl_kernel_kptr_restrict_value"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.kptr_restrict\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.kptr_restrict\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Enable Randomized Layout of Virtual Address Space
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.randomize_va_space.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.randomize_va_space="2"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.randomize_va_space")
printf -v formatted_output "%s = %s" "$stripped_key" "2"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.randomize_va_space\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.randomize_va_space\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable storing core dumps
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.core_pattern.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.core_pattern="|/bin/false"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.core_pattern")
printf -v formatted_output "%s = %s" "$stripped_key" "|/bin/false"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.core_pattern\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.core_pattern\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Restrict Access to Kernel Message Buffer
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.dmesg_restrict.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      # comment out "kernel.dmesg_restrict" matches to preserve user data
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.dmesg_restrict="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.dmesg_restrict")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.dmesg_restrict\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.dmesg_restrict\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Kernel Image Loading
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.kexec_load_disabled.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.kexec_load_disabled="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.kexec_load_disabled")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.kexec_load_disabled\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.kexec_load_disabled\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disallow kernel profiling by unprivileged users
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.perf_event_paranoid.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.perf_event_paranoid="2"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.perf_event_paranoid")
printf -v formatted_output "%s = %s" "$stripped_key" "2"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.perf_event_paranoid\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.perf_event_paranoid\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable Access to Network bpf() Syscall From Unprivileged Processes
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.unprivileged_bpf_disabled.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.unprivileged_bpf_disabled="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.unprivileged_bpf_disabled")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.unprivileged_bpf_disabled\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.unprivileged_bpf_disabled\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Restrict usage of ptrace to descendant processes
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*kernel.yama.ptrace_scope.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w kernel.yama.ptrace_scope="1"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^kernel.yama.ptrace_scope")
printf -v formatted_output "%s = %s" "$stripped_key" "1"
if LC_ALL=C grep -q -m 1 -i -e "^kernel.yama.ptrace_scope\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^kernel.yama.ptrace_scope\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Harden the operation of the BPF just-in-time compiler
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*net.core.bpf_jit_harden.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w net.core.bpf_jit_harden="2"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^net.core.bpf_jit_harden")
printf -v formatted_output "%s = %s" "$stripped_key" "2"
if LC_ALL=C grep -q -m 1 -i -e "^net.core.bpf_jit_harden\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^net.core.bpf_jit_harden\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
# Disable the use of user namespaces
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf; do
  matching_list=$(grep -P '^(?!#).*[\s]*user.max_user_namespaces.*$' $f | uniq )
  if ! test -z "$matching_list"; then
    while IFS= read -r entry; do
      escaped_entry=$(sed -e 's|/|\\/|g' <<< "$entry")
      sed -i "s/^$${escaped_entry}$/# &/g" $f
    done <<< "$matching_list"
  fi
done
/sbin/sysctl -q -n -w user.max_user_namespaces="0"
sed_command=('sed' '-i')
if test -L "/etc/sysctl.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^user.max_user_namespaces")
printf -v formatted_output "%s = %s" "$stripped_key" "0"
if LC_ALL=C grep -q -m 1 -i -e "^user.max_user_namespaces\\>" "/etc/sysctl.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^user.max_user_namespaces\\>.*/$escaped_formatted_output/gi" "/etc/sysctl.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/sysctl.conf" >> "/etc/sysctl.conf"
    printf '%s\n' "$formatted_output" >> "/etc/sysctl.conf"
fi
#### Services
## Base Services
# Disable KDump Kernel Crash Analyzer (kdump)
SYSTEMCTL_EXEC='/usr/bin/systemctl'
"$SYSTEMCTL_EXEC" disable 'kdump.service'
"$SYSTEMCTL_EXEC" mask 'kdump.service'
# Disable socket activation if we have a unit file for it
if "$SYSTEMCTL_EXEC" list-unit-files | grep -q '^kdump.socket'; then
    "$SYSTEMCTL_EXEC" mask 'kdump.socket'
fi
## Application Whitelisting Daemon
# Enable the File Access Policy Service
systemctl enable fapolicyd.service
## Mail Server Software
# Prevent Unrestricted Mail Relaying
# Remediation is applicable only in certain platforms
if ! grep -q ^smtpd_client_restrictions /etc/postfix/main.cf; then
	echo "smtpd_client_restrictions = permit_mynetworks,reject" >> /etc/postfix/main.cf
else
	sed -i "s/^smtpd_client_restrictions.*/smtpd_client_restrictions = permit_mynetworks,reject/g" /etc/postfix/main.cf
fi
## Network Time Protocol
# Disable chrony daemon from acting as server
sed_command=('sed' '-i')
if test -L "/etc/chrony.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^port")
printf -v formatted_output "%s %s" "$stripped_key" "0"
if LC_ALL=C grep -q -m 1 -i -e "^port\\>" "/etc/chrony.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^port\\>.*/$escaped_formatted_output/gi" "/etc/chrony.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/chrony.conf" >> "/etc/chrony.conf"
    printf '%s\n' "$formatted_output" >> "/etc/chrony.conf"
fi
# Disable network management of chrony daemon
sed_command=('sed' '-i')
if test -L "/etc/chrony.conf"; then
    sed_command+=('--follow-symlinks')
fi
stripped_key=$(sed 's/[\^=\$,;+]*//g' <<< "^cmdport")
printf -v formatted_output "%s %s" "$stripped_key" "0"
if LC_ALL=C grep -q -m 1 -i -e "^cmdport\\>" "/etc/chrony.conf"; then
    escaped_formatted_output=$(sed -e 's|/|\\/|g' <<< "$formatted_output")
    "$${sed_command[@]}" "s/^cmdport\\>.*/$escaped_formatted_output/gi" "/etc/chrony.conf"
else
    cce=""
    printf '\n# Per %s: Set %s in %s\n' "$cce" "$formatted_output" "/etc/chrony.conf" >> "/etc/chrony.conf"
    printf '%s\n' "$formatted_output" >> "/etc/chrony.conf"
fi
# Configure Time Service Maxpoll Interval
var_time_service_set_maxpoll='16'
pof="/usr/sbin/pidof"
config_file="/etc/ntp.conf"
$pof ntpd || config_file="/etc/chrony.conf"
sed -i "s/^\(\(server\|pool\|peer\).*maxpoll\) [0-9][0-9]*\(.*\)$/\1 $var_time_service_set_maxpoll \3/" "$config_file"
grep "^\(server\|pool\|peer\)" "$config_file" | grep -v maxpoll | while read -r line ; do
        sed -i "s/$line/& maxpoll $var_time_service_set_maxpoll/" "$config_file"
done
## SSH Server
# Set SSH Client Alive Count Max
var_sshd_set_keepalive='1'
if [ -e "/etc/ssh/sshd_config" ] ; then
    LC_ALL=C sed -i "/^\s*ClientAliveCountMax\s\+/Id" "/etc/ssh/sshd_config"
else
    touch "/etc/ssh/sshd_config"
fi
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    printf '%s\n' "ClientAliveCountMax $var_sshd_set_keepalive" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    printf '%s\n' "ClientAliveCountMax $var_sshd_set_keepalive" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Set SSH Idle Timeout Interval
sshd_idle_timeout_value='600'
LC_ALL=C sed -i "/^\s*ClientAliveInterval\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "ClientAliveInterval $sshd_idle_timeout_value" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "ClientAliveInterval $sshd_idle_timeout_value" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable Compression Or Set Compression to delayed
var_sshd_disable_compression='no'
LC_ALL=C sed -i "/^\s*Compression\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "Compression $var_sshd_disable_compression" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "Compression $var_sshd_disable_compression" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable SSH Access via Empty Passwords
if grep -qP '^#PermitEmptyPasswords\sno$' "/etc/ssh/sshd_config"; then
    sed -i -E "s/^#(PermitEmptyPasswords\sno)$/\1/" /etc/ssh/sshd_config
fi
# Disable GSSAPI Authentication
LC_ALL=C sed -i "/^\s*GSSAPIAuthentication\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "GSSAPIAuthentication no" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "GSSAPIAuthentication no" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable Kerberos Authentication
LC_ALL=C sed -i "/^\s*KerberosAuthentication\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "KerberosAuthentication no" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "KerberosAuthentication no" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable SSH Root Login
LC_ALL=C sed -i "/^\s*PermitRootLogin\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "PermitRootLogin no" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "PermitRootLogin no" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable SSH Support for User Known Hosts
LC_ALL=C sed -i "/^\s*IgnoreUserKnownHosts\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "IgnoreUserKnownHosts yes" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "IgnoreUserKnownHosts yes" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Disable X11 Forwarding
LC_ALL=C sed -i "/^\s*X11Forwarding\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "X11Forwarding no" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "X11Forwarding no" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Do Not Allow SSH Environment Options
LC_ALL=C sed -i "/^\s*PermitUserEnvironment\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "PermitUserEnvironment no" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "PermitUserEnvironment no" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Enable Use of Strict Mode Checking
LC_ALL=C sed -i "/^\s*StrictModes\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "StrictModes yes" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "StrictModes yes" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Enable SSH Warning Banner
LC_ALL=C sed -i "/^\s*Banner\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "Banner /etc/issue" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "Banner /etc/issue" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Enable SSH Print Last Log
LC_ALL=C sed -i "/^\s*PrintLastLog\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "PrintLastLog yes" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "PrintLastLog yes" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# Force frequent session key renegotitation
var_rekey_limit_size='1G'
var_rekey_limit_time='1h'
LC_ALL=C sed -i "/^\s*RekeyLimit\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "RekeyLimit $var_rekey_limit_size $var_rekey_limit_time" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "RekeyLimit $var_rekey_limit_size $var_rekey_limit_time" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
# SSH Server uses strong entropy to seed
LC_ALL=C sed -i "/^\s*SSH_USE_STRONG_RNG=/d" "/etc/sysconfig/sshd"
cp "/etc/sysconfig/sshd" "/etc/sysconfig/sshd.bak"
line_number="$(LC_ALL=C grep -n "^#\s*SSH_USE_STRONG_RNG" "/etc/sysconfig/sshd.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "SSH_USE_STRONG_RNG=32" >> "/etc/sysconfig/sshd"
else
    head -n "$(( line_number - 1 ))" "/etc/sysconfig/sshd.bak" > "/etc/sysconfig/sshd"
    echo "SSH_USE_STRONG_RNG=32" >> "/etc/sysconfig/sshd"
    tail -n "+$(( line_number ))" "/etc/sysconfig/sshd.bak" >> "/etc/sysconfig/sshd"
fi
rm "/etc/sysconfig/sshd.bak"
# Prevent remote hosts from connecting to the proxy display
LC_ALL=C sed -i "/^\s*X11UseLocalhost\s\+/Id" "/etc/ssh/sshd_config"
cp "/etc/ssh/sshd_config" "/etc/ssh/sshd_config.bak"
line_number="$(LC_ALL=C grep -n "^Match" "/etc/ssh/sshd_config.bak" | LC_ALL=C sed 's/:.*//g')"
if [ -z "$line_number" ]; then
    echo "X11UseLocalhost yes" >> "/etc/ssh/sshd_config"
else
    head -n "$(( line_number - 1 ))" "/etc/ssh/sshd_config.bak" > "/etc/ssh/sshd_config"
    echo "X11UseLocalhost yes" >> "/etc/ssh/sshd_config"
    tail -n "+$(( line_number ))" "/etc/ssh/sshd_config.bak" >> "/etc/ssh/sshd_config"
fi
rm "/etc/ssh/sshd_config.bak"
## System Security Services Daemon
# Certificate status checking in SSSD
var_sssd_certificate_verification_digest_function='sha1'
MAIN_CONF="/etc/sssd/conf.d/certificate_verification.conf"
found=false
for f in $(echo -n "$MAIN_CONF /etc/sssd/sssd.conf /etc/sssd/conf.d/*.conf"); do
    if [ ! -e "$f" ]; then
        continue
    fi
    if grep -qzosP "[[:space:]]*\[sssd\]([^\n\[]*\n+)+?[[:space:]]*certificate_verification" "$f"; then
            sed -i "s/certificate_verification[^(\n)]*/certificate_verification = ocsp_dgst = $var_sssd_certificate_verification_digest_function/" "$f"
            found=true
    elif grep -qs "[[:space:]]*\[sssd\]" "$f"; then
            sed -i "/[[:space:]]*\[sssd\]/a certificate_verification = ocsp_dgst = $var_sssd_certificate_verification_digest_function" "$f"
            found=true
    fi
done
if ! $found ; then
    file=$(echo "$MAIN_CONF /etc/sssd/sssd.conf /etc/sssd/conf.d/*.conf" | cut -f1 -d ' ')
    mkdir -p "$(dirname "$file")"
    echo -e "[sssd]\ncertificate_verification = ocsp_dgst = $var_sssd_certificate_verification_digest_function" >> "$file"
fi
if [ -e "$MAIN_CONF" ]; then
    chown root:root "$MAIN_CONF"
	chmod 600 "$MAIN_CONF"
fi
# Enable Certmap in SSSD
cat << EOF >> /etc/sssd/sssd.conf
[certmap/testing.test/rule_name]
matchrule = <SAN>.*EDIPI@mil
maprule = (userCertificate;binary={cert!bin})
domains = testing.test
EOF
# Enable Smartcards in SSSD
found=false
for f in $(echo -n "/etc/sssd/sssd.conf"); do
    if [ ! -e "$f" ]; then
        continue
    fi
    if grep -qzosP "[[:space:]]*\[pam\]([^\n\[]*\n+)+?[[:space:]]*pam_cert_auth" "$f"; then
            sed -i "s/pam_cert_auth[^(\n)]*/pam_cert_auth = True/" "$f"
            found=true
    elif grep -qs "[[:space:]]*\[pam\]" "$f"; then
            sed -i "/[[:space:]]*\[pam\]/a pam_cert_auth = True" "$f"
            found=true
    fi
done
if ! $found ; then
    file=$(echo "/etc/sssd/sssd.conf" | cut -f1 -d ' ')
    mkdir -p "$(dirname "$file")"
    echo -e "[pam]\npam_cert_auth = True" >> "$file"
fi
if [ -f /usr/bin/authselect ]; then
    if authselect check; then
        if ! authselect check; then
        echo "
        authselect integrity check failed. Remediation aborted!
        This remediation could not be applied because an authselect profile was not selected or the selected profile is not intact.
        It is not recommended to manually edit the PAM files when authselect tool is available.
        In cases where the default authselect profile does not cover a specific demand, a custom authselect profile is recommended."
        exit 1
        fi
        authselect enable-feature with-smartcard
        authselect apply-changes -b
    fi
else
    if ! grep -qP '^\s*auth\s+'"sufficient"'\s+pam_sss.so\s*.*' "/etc/pam.d/smartcard-auth"; then
        if [ "$(grep -cP '^\s*auth\s+.*\s+pam_sss.so\s*' "/etc/pam.d/smartcard-auth")" -eq 1 ]; then
            sed -i -E --follow-symlinks 's/^(\s*auth\s+).*(\bpam_sss.so.*)/\1'"sufficient"' \2/' "/etc/pam.d/smartcard-auth"
        else
            echo 'auth    '"sufficient"'    pam_sss.so' >> "/etc/pam.d/smartcard-auth"
        fi
    fi
    if ! grep -qP '^\s*auth\s+'"sufficient"'\s+pam_sss.so\s*.*\sallow_missing_name\b' "/etc/pam.d/smartcard-auth"; then
        sed -i -E --follow-symlinks '/\s*auth\s+'"sufficient"'\s+pam_sss.so.*/ s/$/ allow_missing_name/' "/etc/pam.d/smartcard-auth"
    fi
    if ! grep -qP '^\s*auth\s+'"\[success=done authinfo_unavail=ignore ignore=ignore default=die\]"'\s+pam_sss.so\s*.*' "/etc/pam.d/system-auth"; then
        if [ "$(grep -cP '^\s*auth\s+.*\s+pam_sss.so\s*' "/etc/pam.d/system-auth")" -eq 1 ]; then
            sed -i -E --follow-symlinks 's/^(\s*auth\s+).*(\bpam_sss.so.*)/\1'"\[success=done authinfo_unavail=ignore ignore=ignore default=die\]"' \2/' "/etc/pam.d/system-auth"
        else
            echo 'auth    '"\[success=done authinfo_unavail=ignore ignore=ignore default=die\]"'    pam_sss.so' >> "/etc/pam.d/system-auth"
        fi
    fi
    if ! grep -qP '^\s*auth\s+'"\[success=done authinfo_unavail=ignore ignore=ignore default=die\]"'\s+pam_sss.so\s*.*\stry_cert_auth\b' "/etc/pam.d/system-auth"; then
        sed -i -E --follow-symlinks '/\s*auth\s+'"\[success=done authinfo_unavail=ignore ignore=ignore default=die\]"'\s+pam_sss.so.*/ s/$/ try_cert_auth/' "/etc/pam.d/system-auth"
    fi
fi
## USBGuard daemon
# Enable the USBGuard Service
SYSTEMCTL_EXEC='/usr/bin/systemctl'
"$SYSTEMCTL_EXEC" unmask 'usbguard.service'
"$SYSTEMCTL_EXEC" start 'usbguard.service'
"$SYSTEMCTL_EXEC" enable 'usbguard.service'
# Log USBGuard daemon audit events using Linux Audit
if [ -e "/etc/usbguard/usbguard-daemon.conf" ] ; then
    LC_ALL=C sed -i "/^\s*AuditBackend=/d" "/etc/usbguard/usbguard-daemon.conf"
else
    touch "/etc/usbguard/usbguard-daemon.conf"
fi
cp "/etc/usbguard/usbguard-daemon.conf" "/etc/usbguard/usbguard-daemon.conf.bak"
printf '%s\n' "AuditBackend=LinuxAudit" >> "/etc/usbguard/usbguard-daemon.conf"
rm "/etc/usbguard/usbguard-daemon.conf.bak"
# Generate USBGuard Policy
USBGUARD_CONF=/etc/usbguard/rules.conf
if [ ! -f "$USBGUARD_CONF" ] || [ ! -s "$USBGUARD_CONF" ]; then
    usbguard generate-policy > $USBGUARD_CONF
    if [ ! -s "$USBGUARD_CONF" ]; then
        echo "# No USB devices found" > $USBGUARD_CONF
    fi
    chmod 600 $USBGUARD_CONF
    SYSTEMCTL_EXEC='/usr/bin/systemctl'
    "$SYSTEMCTL_EXEC" unmask 'usbguard.service'
    "$SYSTEMCTL_EXEC" restart 'usbguard.service'
    "$SYSTEMCTL_EXEC" enable 'usbguard.service'
fi
%end

%post
# Temp setup nopasswd sudoers
echo "packer ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers.d/packer
chage -I -1 -m 0 -M 99999 -E -1 packer
%end
