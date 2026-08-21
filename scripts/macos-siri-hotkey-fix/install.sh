#!/usr/bin/env bash
# install.sh - build, sign, and register siri_preempt as a per-user LaunchAgent.
#
# Fixes: Cmd+Shift+Space opening Siri AI (com.apple.campo) on top of
# 1Password's Quick Access panel on macOS 27, causing 1Password to lose
# focus and self-dismiss. See siri_preempt.m for full root-cause writeup.
#
# This script does NOT call `launchctl bootstrap` for you -- registering a
# persistent KeepAlive LaunchAgent is left as a manual last step you run
# yourself, on purpose. Review the printed command before running it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"
BIN_PATH="$BIN_DIR/siri_preempt"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT_PATH="$AGENT_DIR/com.adamdurham.siripreempt.plist"

echo "==> Building siri_preempt"
mkdir -p "$BIN_DIR"
clang -O2 -o "$BIN_PATH" "$SCRIPT_DIR/siri_preempt.m" -framework Cocoa -framework ApplicationServices
codesign -s - "$BIN_PATH"
echo "    built: $BIN_PATH"

echo "==> Installing LaunchAgent plist"
mkdir -p "$AGENT_DIR"
sed "s|__HOME__|$HOME|g" "$SCRIPT_DIR/com.adamdurham.siripreempt.plist" > "$AGENT_PATH"
plutil -lint "$AGENT_PATH"
echo "    installed: $AGENT_PATH"

echo
echo "==> Manual steps required (cannot be automated):"
echo
echo "1. Grant Accessibility permission to the binary:"
echo "     open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
echo "   Click '+', press Cmd+Shift+G, paste this path, then enable its toggle:"
echo "     $BIN_PATH"
echo
echo "2. Load the LaunchAgent (auto-starts on every future login/reboot after this):"
echo "     launchctl bootstrap gui/\$(id -u) $AGENT_PATH"
echo
echo "3. Verify it's running:"
echo "     launchctl print gui/\$(id -u)/com.adamdurham.siripreempt | head -6"
echo "     tail -f /tmp/siri_preempt.log   # watch for 'combo detected' when testing"
echo
echo "To uninstall:"
echo "     launchctl bootout gui/\$(id -u)/com.adamdurham.siripreempt"
echo "     rm '$AGENT_PATH' '$BIN_PATH'"
echo "   Then remove the Accessibility entry manually in System Settings."
