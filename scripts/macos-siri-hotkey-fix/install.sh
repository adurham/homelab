#!/usr/bin/env bash
# install.sh - build, sign, and register SiriPreempt.app as a per-user
# LaunchAgent.
#
# Fixes: Cmd+Shift+Space opening Siri AI (com.apple.campo) on top of
# 1Password's Quick Access panel on macOS 27, causing 1Password to lose
# focus and self-dismiss. See siri_preempt.m for full root-cause writeup.
#
# IMPORTANT: this must be packaged as a minimal .app bundle (LSUIElement,
# no Dock icon), not run as a bare CLI binary. Confirmed by direct testing:
# a bare Mach-O binary at ~/bin/siri_preempt, even with a valid-looking
# Input Monitoring grant showing enabled in System Settings, reliably
# failed with "FAILED to create event tap" (CGEventTapCreate returned
# NULL) every time it was spawned by launchd -- while the *identical*
# binary worked fine when run manually from an interactive shell. Wrapping
# the exact same executable in a minimal .app bundle with its own
# CFBundleIdentifier resolved it: launchd-spawned processes need a real
# app bundle for the Input Monitoring/Accessibility TCC grant to bind
# reliably, a bare executable path is not sufficient. Do not "simplify"
# this back to a bare binary without re-testing via `launchctl bootstrap`
# specifically (not just running it by hand -- that will look like it
# works and then silently fail once handed to launchd).
#
# This script does NOT call `launchctl bootstrap` for you -- registering a
# persistent KeepAlive LaunchAgent is left as a manual last step you run
# yourself, on purpose. Review the printed command before running it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/Applications/SiriPreempt.app"
EXEC_PATH="$APP_DIR/Contents/MacOS/SiriPreempt"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT_PATH="$AGENT_DIR/com.adamdurham.siripreempt.plist"

echo "==> Building siri_preempt"
BUILD_TMP="$(mktemp -t siri_preempt)"
clang -O2 -fobjc-arc -o "$BUILD_TMP" "$SCRIPT_DIR/siri_preempt.m" -framework Cocoa -framework ApplicationServices

echo "==> Packaging as a minimal .app bundle (required -- see header comment)"
mkdir -p "$APP_DIR/Contents/MacOS"
cp "$BUILD_TMP" "$EXEC_PATH"
rm -f "$BUILD_TMP"
chmod +x "$EXEC_PATH"

cat > "$APP_DIR/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SiriPreempt</string>
    <key>CFBundleIdentifier</key>
    <string>com.adamdurham.siripreempt</string>
    <key>CFBundleName</key>
    <string>SiriPreempt</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
EOF

codesign -f -s - "$APP_DIR"
echo "    built: $APP_DIR"

echo "==> Installing LaunchAgent plist"
mkdir -p "$AGENT_DIR"
sed "s|__HOME__|$HOME|g" "$SCRIPT_DIR/com.adamdurham.siripreempt.plist" > "$AGENT_PATH"
plutil -lint "$AGENT_PATH"
echo "    installed: $AGENT_PATH"

echo
echo "==> Manual steps required (cannot be automated):"
echo
echo "1. Grant Input Monitoring permission (NOT Accessibility -- this tool"
echo "   only needs to listen for one key combo, not control the UI):"
echo "     open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'"
echo "   Click '+', press Cmd+Shift+G, paste this path, then enable its toggle:"
echo "     $EXEC_PATH"
echo
echo "2. Load the LaunchAgent (auto-starts on every future login/reboot after this):"
echo "     launchctl bootstrap gui/\$(id -u) $AGENT_PATH"
echo
echo "3. Verify it's running:"
echo "     launchctl print gui/\$(id -u)/com.adamdurham.siripreempt | grep -E 'state|last exit'"
echo "     tail -f /tmp/siri_preempt.log   # watch for 'combo detected' when testing"
echo
echo "   If 'last exit code' is 1 and the log shows"
echo "   'FAILED to create event tap', the Input Monitoring grant did not"
echo "   bind -- re-check step 1, and confirm the granted path exactly"
echo "   matches: $EXEC_PATH"
echo
echo "To uninstall:"
echo "     launchctl bootout gui/\$(id -u)/com.adamdurham.siripreempt"
echo "     rm '$AGENT_PATH'"
echo "     rm -rf '$APP_DIR'"
echo "   Then remove the Input Monitoring entry manually in System Settings."
