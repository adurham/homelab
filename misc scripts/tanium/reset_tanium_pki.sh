#!/bin/sh

# Updated log file location to persist after reboots
LOG_FILE="/opt/Tanium/TaniumClient/Data/tanium_reset.log"

# Define key file paths
BACKUP_FILE="/opt/Tanium/TaniumClient/Backup/tanium-init.dat"
PKI_DB_FILE="/opt/Tanium/TaniumClient/pki.db"

# === MAIN LOGIC ===
do_reset() {
    echo "$(date): Worker process started. Performing validation and reset." >> $LOG_FILE

    # 1. --- PRE-CHECK: Verify the backup file exists ---
    if [ ! -f "$BACKUP_FILE" ]; then
        echo "$(date): FATAL ERROR - Backup file not found at ${BACKUP_FILE}. Aborting." >> $LOG_FILE
        exit 1
    fi
    echo "$(date): PRE-CHECK PASSED - Backup file found." >> $LOG_FILE

    # Capture the 'before' timestamp of the pki.db file
    TIMESTAMP_BEFORE=$(stat -c %Y "$PKI_DB_FILE")
    echo "$(date): pki.db timestamp before reset: ${TIMESTAMP_BEFORE}" >> $LOG_FILE

    echo "$(date): Stopping Tanium client..." >> $LOG_FILE
    systemctl stop taniumclient
    sleep 3

    echo "$(date): PKI reset command executing..." >> $LOG_FILE
    /opt/Tanium/TaniumClient/TaniumClient pki reset "$BACKUP_FILE" >> $LOG_FILE 2>&1
    
    # Give a moment for the file system to update
    sleep 1

    # 2. --- POST-CHECK: Verify the pki.db file was modified ---
    TIMESTAMP_AFTER=$(stat -c %Y "$PKI_DB_FILE")
    echo "$(date): pki.db timestamp after reset: ${TIMESTAMP_AFTER}" >> $LOG_FILE

    if [ "$TIMESTAMP_BEFORE" -ne "$TIMESTAMP_AFTER" ]; then
        echo "$(date): SUCCESS - pki.db timestamp has changed. Reset was successful." >> $LOG_FILE
    else
        echo "$(date): FAILURE - pki.db timestamp did not change. Reset likely failed." >> $LOG_FILE
    fi

    echo "$(date): Starting Tanium client..." >> $LOG_FILE
    systemctl start taniumclient

    echo "$(date): Worker process finished." >> $LOG_FILE
}


# === LAUNCHER LOGIC ===
case "$1" in
    --worker)
        # This is the detached process. Run the reset logic.
        do_reset
        ;;
    *)
        # This is the initial execution by Tanium.

        # Determine the absolute path of this script.
        case "$0" in
            /*) SCRIPT_PATH="$0" ;;
             *) SCRIPT_PATH="$(pwd)/$0" ;;
        esac

        echo "$(date): Launcher started. Detaching worker process using systemd-run..." >> $LOG_FILE

        # Use systemd-run to launch the worker in a new, separate scope
        systemd-run --scope --nice=10 /bin/sh "${SCRIPT_PATH}" --worker
        
        echo "$(date): Launcher has finished. Worker is now running independently." >> $LOG_FILE
        exit 0
        ;;
esac