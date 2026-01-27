# Windows Server Template Creation Guide

This guide details the process of creating a "Golden Image" template for Windows Server 2022 on Proxmox VE.

## 1. Prerequisites

Ensure the following ISOs are available on your Proxmox node's storage (e.g., `local:iso`):

- **Windows Server ISO**: `SERVER_EVAL_x64FRE_en-us.iso`
- **VirtIO Drivers ISO**: `virtio-win-0.1.285.iso`

## 2. Infrastructure Provisioning

We use Ansible to provision the VM shell with the correct hardware settings (UEFI, TPM, VirtIO SCSI, etc.).

**Run the Playbook:**

```bash
cd ~/repos/homelab
ansible-playbook -i ansible/inventory/proxmox.yml ansible/build_windows_template.yml -e "vm_id=9000 vm_name=win-2022-source"
```

*Note: You can customize `vm_id` and `vm_name` as needed.*

## 3. Windows Installation

1. **Start the VM**: Open the Proxmox Console for the new VM (e.g., ID 9000) and click **Start**.
2. **Boot from CD**: Press any key to boot from the CD/DVD if prompted.
3. **Windows Setup**:
    - Select Language/Time/Keyboard.
    - Click **Install Now**.
    - Select **Windows Server 2022 Standard Evaluation (Desktop Experience)**.
    - Accept license terms.
    - Select **Custom: Install Windows only (advanced)**.
4. **Load Storage Driver**:
    - *Problem*: "We couldn't find any drives."
    - *Action*: Click **Load Driver** -> **Browse**.
    - Navigate to `virtio-win-0.1.285` (CD Drive) -> `viostor` -> `2k22` -> `amd64`.
    - Select **Red Hat VirtIO SCSI controller** (Note: This is the VirtIO Block driver).
    - Click **Next**. The 60GB drive should appear.
5. **Install**: Select the drive and click **Next**. Windows will install and reboot.

## 4. Post-Installation Configuration

### A. Initial Setup

1. Set the Administrator password.
2. Login to the desktop.

### B. Install Drivers

1. Open **File Explorer** and go to `D:` or `E:` (VirtIO CD).
2. Run `virtio-win-gt-x64.exe` (Guest Tools Installer).
3. Accept defaults. This effectively installs:
    - **QEMU Guest Agent**
    - **VirtIO Network Driver** (NetKVM) - You should get network connectivity after this.
    - **VirtIO Balloon Driver**
    - **VirtIO Serial Driver**

### C. Enable Remote Desktop (Optional)

- `Settings` -> `System` -> `Remote Desktop` -> `On`.

### D. Windows Updates

- Run Windows Update to patch the system to the latest level. Reboot as required.

## 5. Sysprep and Template Conversion

To ensure unique SIDs when cloning, we must Sysprep the machine.

1. **Open PowerShell** as Administrator.
2. **Run Sysprep**:

    ```powershell
    C:\Windows\System32\Sysprep\sysprep.exe /generalize /oobe /shutdown
    ```

    - `/generalize`: Removes system-specific data (SID, logs).
    - `/oobe`: Forces "Out of Box Experience" on next boot.
    - `/shutdown`: Shuts down the VM automatically.

3. **Convert to Template**:
    - Once the VM is shutdown (Status: Stopped), right-click the VM in Proxmox.
    - Select **Convert to Template**.

## 6. Usage (Cloning)

To deploy a new Server from this template:

1. Right-click the Template -> **Clone**.
2. Select **Full Clone** (for independence) or **Linked Clone** (for speed/disk savings).
3. Boot the new VM. It will effectively treat itself as a fresh installation (OOBE).
