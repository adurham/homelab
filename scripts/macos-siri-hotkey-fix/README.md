# macOS Siri / 1Password Cmd+Shift+Space conflict fix

**Machine:** Personal MacBook, macOS 27.0 beta (build 26A5416b, "Tahoe"-era with the new merged Spotlight/Siri redesign).

**Symptom:** Pressing Cmd+Shift+Space (1Password's Quick Access global shortcut) opened 1Password's quick bar, then a beat later Siri popped up on top of it and 1Password's panel self-dismissed (it lost focus/key-window status when Siri activated).

## Root cause

macOS 27 introduced a new merged Spotlight/Siri app, **Siri AI.app**
(bundle id `com.apple.campo`, process name `Siri AI`), distinct from the
classic `Siri.app`. This new app intercepts Cmd+Shift+Space as an internal
invocation gesture.

This is **not** the documented/configurable Siri keyboard shortcut. Every
classic Siri/Spotlight shortcut preference was checked and found already
disabled or unrelated:

- `com.apple.Siri` → `KeyboardShortcutPreSAE` / `KeyboardShortcutSAE`: both `enabled = 0`
- `com.apple.symbolichotkeys.plist` → `AppleSymbolicHotKeys` id `176` (classic Siri hotkey): `enabled = 0`
- `com.apple.symbolichotkeys.plist` ids `60`/`61`/`64` (Spotlight cmd+space variants): all `enabled = 0`, and none are even bound to Cmd+Shift+Space
- `com.apple.Spotlight`, `com.apple.assistant*`, `com.apple.campo` itself (via `defaults read` and a `defaults find campo` sweep), ByHost overrides: nothing relevant

A raw `CGEventTap` keylogger confirmed the actual OS-level key event
(`keycode=49` [space], `cmd=1 shift=1`, `rawflags=1179914`) is a single
real physical keypress — not a synthetic conflict — and `log stream`
showed it being dispatched to **both** `Siri AI[pid]` (com.apple.campo)
and 1Password's own hotkey listener independently. They are two
independent global-hotkey registrations reacting to the same physical
key combo; neither "owns" it exclusively at the OS level.

Siri AI's invocation-hotkey binding for this combo is not exposed via any
readable `defaults`/plist domain on this beta build (searched every user
and system preference domain, the legacy symbolic-hotkey table, and
string tables in `Siri AI.app`, `CampoUIServices.framework`,
`SpotlightUIServices.framework`, etc. — nothing). It appears to be
hardcoded in this build.

`launchctl bootout gui/$(id -u)/com.apple.campo` was also tried directly,
to see if Siri AI's own LaunchAgent could simply be disabled: it fails
with `"Operation not permitted while System Integrity Protection is
engaged"`. Apple's `com.apple.campo` LaunchAgent is SIP-protected and
cannot be unloaded without disabling SIP system-wide — a much bigger
tradeoff than this workaround.

## Approaches tried and rejected

1. **Disable Siri's classic shortcuts** (`KeyboardShortcutSAE` /
   `KeyboardShortcutPreSAE` / symbolic hotkey 176) — already disabled by
   default, had no effect: Siri AI (`com.apple.campo`) is a different
   code path than classic `Siri.app`.
2. **Disable Siri entirely** (`defaults write com.apple.assistant.support
   "Assistant Enabled" -bool false`) — works, confirmed via `log stream`
   (`Siri[pid] ... Exiting early, Siri is either disabled or restricted`),
   but kills Siri everywhere, not just this one hotkey. Kept as a known
   fallback, not the chosen fix.
3. **Change 1Password's Quick Access shortcut to something else** — the
   objectively simplest fix. Explicitly considered and rejected: the
   requirement was to keep using Cmd+Shift+Space for 1Password
   specifically and make Siri AI stay out of the way, not remap
   1Password around Siri AI's undocumented behavior.
4. **Disable/unload Siri AI's own LaunchAgent** (`launchctl bootout
   gui/$(id -u)/com.apple.campo`) — fails, blocked by SIP (see above).
5. **Active (blocking) CGEventTap that swallows the keystroke** — also
   silently killed 1Password's own response to the same combo. Proved
   that 1Password and Siri AI are independent listeners on the same raw
   key event, not competing for a single OS-level registration; a
   session-wide tap can't discriminate between them.
6. **Poll `CGWindowListCopyWindowInfo` for Siri AI's window and hide it**
   (unconditionally, not scoped to right after a keypress) — too slow at
   a sustainable poll interval (~15ms). By the time the loop noticed the
   window, 1Password had already lost focus and self-dismissed.
7. **`NSWorkspaceDidActivateApplicationNotification` observer, without a
   polling fallback** — measured directly and rejected: Siri AI has
   `NSApplicationActivationPolicy = 1` (accessory app, like a menu-bar
   helper). A 30-second passive watch sampling `isActive`/`hidden` every
   5ms while repeatedly triggering the combo never observed either
   property change, and the activation notification never fired for
   `com.apple.campo` — yet the panel visibly appeared and dismissed
   1Password every time. This accessory app's activation is either not
   reflected on the standard `NSRunningApplication`/`NSWorkspace`
   observation surface at all, or the state change is real but too brief
   for passive sampling at normal intervals to reliably catch. The
   notification observer is kept in the final version as a
   belt-and-suspenders fast path, in case behavior differs on another
   build, but it is **not** relied on as the primary mechanism.

## Fix: listen-only event tap + short bounded busy-poll

`siri_preempt.m` installs a **listen-only** `CGEventTap` (never blocks or
consumes events — every app, including 1Password, still gets the real
keystroke; autorepeat events from a held-down combo are ignored). The
instant it detects Cmd+Shift+Space, it busy-polls
`NSRunningApplication.isActive`/`.hidden` for Siri AI
(`com.apple.campo`) every 0.5ms for up to ~200ms on a background queue
(not the main queue, so it never blocks the event tap or the
notification observer from receiving further events during the poll).
The moment it sees Siri AI active, it immediately `hide`s Siri AI and
re-`activate`s 1Password (`com.1password.1password`).

This tight, bounded poll is not a compromise or an oversight — per
approach 7 above, it is the **only** mechanism that has actually been
observed, repeatedly, live, to catch this specific accessory app's
activation. It only runs for ~200ms right after a detected keypress, not
continuously, so steady-state CPU is still effectively 0%.

The tap re-enables itself if the OS ever disables it
(`kCGEventTapDisabledByTimeout`/`DisabledByUserInput`), which is
standard practice for long-running taps and prevents this tool from
silently going dark under load without any visible symptom.

Result: 1Password's Quick Access panel opens and stays open; Siri AI
never becomes visible. Siri itself remains fully enabled and usable
everywhere else (this only intercepts one specific hotkey combo).

Confirmed CPU-idle: 0.0% CPU / ~10MB RSS at rest (`ps -o %cpu,%mem`),
negligible battery impact, comparable to any lightweight global-hotkey
utility (Rectangle, BetterTouchTool, etc.). Brief ~200ms poll bursts only
happen right after an actual Cmd+Shift+Space press.

### Why a `.app` bundle, not a bare CLI binary

Confirmed directly by testing: a bare Mach-O binary at `~/bin/siri_preempt`,
even with a valid-looking Input Monitoring grant showing enabled in
System Settings, reliably failed with `"FAILED to create event tap"`
(`CGEventTapCreate` returned `NULL`) every single time it was spawned by
`launchd` via a `LaunchAgent` — while the *identical* binary, run manually
from an interactive terminal, worked every time. Adding
`LimitLoadToSessionType: Aqua` to the LaunchAgent plist did not fix it.

The resolution: wrap the exact same executable in a minimal `.app` bundle
(`~/Applications/SiriPreempt.app`, `LSUIElement: true` so it has no Dock
icon or menu bar presence, own `CFBundleIdentifier`) and point the
LaunchAgent at the executable inside that bundle. This is the standard,
correct pattern here — a bare executable path is not sufficient for the
Input Monitoring/Accessibility TCC grant to bind reliably to a
launchd-spawned process; wrapping it as a proper app bundle with a real
bundle identifier resolved it immediately and consistently.

**Do not "simplify" this back to a bare binary** without re-testing via
an actual `launchctl bootstrap` load (not just running it by hand — that
will look like it works and then silently fail once handed to launchd).

## Install

```
cd scripts/macos-siri-hotkey-fix
./install.sh
```

The script builds the binary, packages it as `~/Applications/SiriPreempt.app`,
code-signs it, and writes the LaunchAgent plist, then prints the manual
steps that can't be automated:

1. Grant the app's executable **Input Monitoring** permission (NOT
   Accessibility — a listen-only keyboard tap only needs
   `kTCCServiceListenEvent`; Accessibility grants strictly more,
   including synthetic-event posting and UI control, which this tool
   does not use and should not request) in System Settings > Privacy &
   Security > Input Monitoring. macOS doesn't auto-prompt for this —
   add it manually via "+", Cmd+Shift+G to type the exact path:
   `~/Applications/SiriPreempt.app/Contents/MacOS/SiriPreempt`.
2. Run `launchctl bootstrap gui/$(id -u) <agent-plist-path>` yourself to
   load the LaunchAgent (`RunAtLoad` + `KeepAlive` means it then
   auto-starts on every future login/reboot without further action).

If you rebuild the binary, its code signature (and thus cdhash) changes,
which can invalidate the TCC grant — re-check step 1 after any rebuild.

## Uninstall

```
launchctl bootout gui/$(id -u)/com.adamdurham.siripreempt
rm ~/Library/LaunchAgents/com.adamdurham.siripreempt.plist
rm -rf ~/Applications/SiriPreempt.app
```

Then remove the Input Monitoring entry manually in System Settings >
Privacy & Security > Input Monitoring.

## Caveats

- Depends on internal, undocumented Siri AI behavior (`com.apple.campo`
  bundle id, accessory activation policy, `hide`/`isActive`/`hidden`
  `NSRunningApplication` state) on a **beta** OS build. Re-evaluate on
  the next macOS build — Apple may change this behavior or expose a real
  setting, which would make this whole tool unnecessary. Consider filing
  Feedback (feedbackassistant.apple.com) about the undocumented,
  non-configurable hotkey interception.
- `[onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps]`
  is deprecated (macOS 14+); macOS's cooperative activation model means a
  background process's request to activate another app may simply be
  ignored on a future build. This is the most fragile part of the whole
  approach — if 1Password stops regaining focus after a macOS update,
  this is the first place to look.
- Event taps receive no events while `SecureEventInput` is engaged (e.g.
  focus is in a password field). Pressing the combo in a secure field is
  invisible to this tool.
- If the Input Monitoring TCC grant is ever revoked (e.g. after a rebuild
  changes the app's signature), `CGEventTapCreate` returns `NULL` and the
  process exits with status 1. Combined with the LaunchAgent's
  `KeepAlive=true`, this becomes a silent respawn loop until the
  permission is re-granted. Check `tail -f /tmp/siri_preempt.log` if the
  fix silently stops working.
- If 1Password ever changes its bundle id or its Quick Access shortcut
  away from Cmd+Shift+Space, update the target combo / bundle id
  constants in `siri_preempt.m` accordingly.
