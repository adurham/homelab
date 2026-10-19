#!/bin/bash
# Install the YubiKey sudo fast-path on a Mac.
#
#   sudo ./yk-sudo-setup.sh [/path/to/pam_yk.so]
#
# Flags (all optional):
#   --no-tid         do NOT add pam_tid.so to sudo_local. Required on headless
#                    boxes: pam_tid returns PAM_SUCCESS with no touch when no
#                    GUI session owns the console (verified on Mac Studio),
#                    which would make sudo passwordless.
#   --key-first      Move "auth include sudo_local" to the top of
#                    /etc/pam.d/sudo, ahead of any pre-existing auth line.
#                    Needed where another `sufficient` module (e.g. the
#                    Homebrew pam_ssh_agent line on the studios) would
#                    otherwise authenticate first and skip the key check.
#   --no-timeout0    Do not write /etc/sudoers.d/001_yk_timeout. Use on hosts
#                    where the key is normally absent: timestamp_timeout=0
#                    forces a PAM round trip (and a 1Password agent signature)
#                    on every sudo, which is pointless without the key present.
#
# Safe by construction: the stack it writes only ever SHORT-CIRCUITS. Key
# absent -> the module fails and control falls through to whatever the host
# already had (Touch ID, password, agent). Nothing here can lock you out.
set -u
MODULE_SRC=""
NO_TID=0
KEY_FIRST=0
NO_TIMEOUT0=0
for arg in "$@"; do
    case "$arg" in
        --no-tid)       NO_TID=1 ;;
        --key-first)    KEY_FIRST=1 ;;
        --no-timeout0)  NO_TIMEOUT0=1 ;;
        --*)            echo "unknown flag: $arg" >&2; exit 2 ;;
        *)              MODULE_SRC="$arg" ;;
    esac
done

PAM_DIR=/usr/local/lib/pam
BK=/var/db/ykrollback
STAMP=$(date +%Y%m%d-%H%M%S)

if [ "$(id -u)" != 0 ]; then echo "run me with sudo"; exit 1; fi
if [ -z "$MODULE_SRC" ] || [ ! -f "$MODULE_SRC" ]; then echo "usage: $0 [flags] /path/to/pam_yk.so"; exit 1; fi

install -d -o root -g wheel -m 0755 "$PAM_DIR" || exit 1
install -d -o root -g wheel -m 0700 "$BK" || exit 1

echo "== backups =="
[ -f /etc/pam.d/sudo ] && cp -p /etc/pam.d/sudo "$BK/sudo.$STAMP" && echo "  /etc/pam.d/sudo -> $BK/sudo.$STAMP"
if [ -f /etc/pam.d/sudo_local ]; then
    cp -p /etc/pam.d/sudo_local "$BK/sudo_local.$STAMP" && echo "  /etc/pam.d/sudo_local -> $BK/sudo_local.$STAMP"
else
    printf '%s\n' "# (no sudo_local existed before $STAMP)" > "$BK/sudo_local.absent.$STAMP"
fi

echo "== install module =="
install -o root -g wheel -m 0755 "$MODULE_SRC" "$PAM_DIR/pam_yk.so" || exit 1
ls -l "$PAM_DIR/pam_yk.so"

echo "== write sudo_local =="
TMP=$(mktemp /tmp/sudo_local.XXXXXX)
{
    echo "# YubiKey fast-path for sudo (installed $STAMP)."
    echo "# Key in  -> silent success, stack stops (automation)."
    if [ "$NO_TID" = 1 ]; then
        echo "# Key out -> falls through to the host's existing auth stack."
    else
        echo "# Key out -> falls through to Touch ID, then password (human approval)."
    fi
    echo "auth       sufficient     $PAM_DIR/pam_yk.so"
    if [ "$NO_TID" = 0 ] && [ -f /usr/lib/pam/pam_tid.so.2 ]; then
        echo "auth       sufficient     pam_tid.so"
    fi
} > "$TMP"
install -o root -g wheel -m 0644 "$TMP" /etc/pam.d/sudo_local || { rm -f "$TMP"; exit 1; }
rm -f "$TMP"
cat /etc/pam.d/sudo_local

if [ "$KEY_FIRST" = 1 ]; then
    echo "== move 'auth include sudo_local' to the top of /etc/pam.d/sudo =="
    if ! grep -q '^[[:space:]]*auth[[:space:]]\+include[[:space:]]\+sudo_local' /etc/pam.d/sudo; then
        echo "REFUSING: /etc/pam.d/sudo has no 'auth include sudo_local' line" >&2
        exit 1
    fi
    TMP=$(mktemp /tmp/pam_sudo.XXXXXX)
    {
        echo "auth       include        sudo_local"
        grep -v -E '^[[:space:]]*auth[[:space:]]+include[[:space:]]+sudo_local' /etc/pam.d/sudo
    } > "$TMP"
    install -o root -g wheel -m 0444 "$TMP" /etc/pam.d/sudo || { rm -f "$TMP"; exit 1; }
    rm -f "$TMP"
    echo "  key check now runs before any other sufficient module:"
    grep -n '^auth' /etc/pam.d/sudo | sed 's/^/    /'
fi

if [ "$NO_TIMEOUT0" = 0 ]; then
    echo "== no sudo caching, so pulling the key takes effect immediately =="
    printf 'Defaults timestamp_timeout=0\n' > /etc/sudoers.d/001_yk_timeout || exit 1
    chmod 0440 /etc/sudoers.d/001_yk_timeout
    if ! visudo -c >/dev/null; then
        echo "sudoers parse failed — removing the file to stay safe"
        rm -f /etc/sudoers.d/001_yk_timeout
        exit 1
    fi
    echo "  installed /etc/sudoers.d/001_yk_timeout"
else
    echo "== leaving sudo timestamp caching untouched (--no-timeout0) =="
fi

echo
echo "Done. With the key inserted, 'sudo <cmd>' should not prompt."
case "$NO_TID$NO_TIMEOUT0$KEY_FIRST" in
    *) echo "Without it, the host's pre-existing auth path applies as before." ;;
esac
echo "Rollback: cp $BK/sudo.$STAMP /etc/pam.d/sudo ; rm -f /etc/pam.d/sudo_local"
