#!/bin/bash
# Add nodev Option to Non-Root Local Partitions
MOUNT_OPTION="nodev"
readarray -t partitions_records < <(findmnt --mtab --raw --evaluate | grep "^/\w" | grep "\s/dev/\w")
for partition_record in "${partitions_records[@]}"; do
    mount_point="$(echo ${partition_record} | cut -d " " -f1)"
    device="$(echo ${partition_record} | cut -d " " -f2)"
    device_type="$(echo ${partition_record} | cut -d " " -f3)"
    mount_point_match_regexp="$(printf "[[:space:]]%s[[:space:]]" $mount_point)"
    if [ "$(grep -c "$mount_point_match_regexp" /etc/fstab)" -eq 0 ]; then
        previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/mtab | head -1 | awk '{print $4}' |
            sed -E "s/(rw|defaults|seclabel|$MOUNT_OPTION)(,|$)//g;s/,$//")
        [ "$previous_mount_opts" ] && previous_mount_opts+=","
        echo "$device $mount_point $device_type defaults,${previous_mount_opts}$MOUNT_OPTION 0 0" >>/etc/fstab
    elif [ "$(grep "$mount_point_match_regexp" /etc/fstab | grep -c "$MOUNT_OPTION")" -eq 0 ]; then
        previous_mount_opts=$(grep "$mount_point_match_regexp" /etc/fstab | awk '{print $4}')
        sed -i "s|\(${mount_point_match_regexp}.*${previous_mount_opts}\)|\1,$MOUNT_OPTION|" /etc/fstab
    fi
    if mkdir -p "$mount_point"; then
        if mountpoint -q "$mount_point"; then
            mount -o remount --target "$mount_point"
        else
            mount --target "$mount_point"
        fi
    fi
done
# Configure tmux to use mouse scrolling
tmux_conf="/etc/tmux.conf"
touch "${tmux_conf}"
echo "set -g mouse on" >> "$tmux_conf"
# Set password policy back for packer user
chage -M 60 packer
chage -m 1 packer
# Disable the packer user
usermod -L packer
# Remove passwordless sudoer file for packer user
rm -f /etc/sudoers.d/packer