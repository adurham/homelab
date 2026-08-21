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
- `com.apple.Spotlight`, `com.apple.assistant*`, ByHost overrides: nothing relevant

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
3. **Active (blocking) CGEventTap that swallows the keystroke** — also
   silently killed 1Password's own response to the same combo. Proved
   that 1Password and Siri AI are independent listeners on the same raw
   key event, not competing for a single OS-level registration; a
   session-wide tap can't discriminate between them.
4. **Poll `CGWindowListCopyWindowInfo` for Siri AI's window and hide it**
   — too slow. By the time a ~15ms poll noticed the window, 1Password had
   already lost focus and self-dismissed.
5. **Listen-only event tap + fixed-step busy-poll race** (first working
   version) — a listen-only `CGEventTap` detected the combo, then
   busy-polled `isActive`/`hidden` every 0.5ms for up to 200ms, hiding
   Siri AI and re-activating 1Password the moment it saw Siri AI active.
   This worked in live testing but is a brute-force timing race, not a
   real fix: it burns CPU during the poll window and has no guarantee of
   winning if Siri AI's activation timing shifts on a different build or
   under load. Superseded by the notification-driven version below.

## Fix: listen-only event tap + NSWorkspace activation notification

`siri_preempt.m` installs a **listen-only** `CGEventTap` (never blocks or
consumes events — every app, including 1Password, still gets the real
keystroke). Detecting Cmd+Shift+Space "arms" a short 500ms window. A
separate `NSWorkspaceDidActivateApplicationNotification` observer reacts
the instant macOS actually activates Siri AI (`com.apple.campo`): if that
happens while armed, it immediately `hide`s Siri AI and re-`activate`s
1Password (`com.1password.1password`) — event-driven on both ends rather
than guessing a timing window with a busy-poll loop.

Result: 1Password's Quick Access panel opens and stays open; Siri AI
never becomes visible. Siri itself remains fully enabled and usable
everywhere else (this only intercepts one specific hotkey combo).

Confirmed CPU-idle: event taps and NSWorkspace notifications are both
interrupt-driven, not polling — 0.0% CPU / ~10MB RSS at rest, negligible
battery impact, comparable to any lightweight global-hotkey utility
(Rectangle, BetterTouchTool, etc.).

## Install

```
cd scripts/macos-siri-hotkey-fix
./install.sh
```

The script builds + code-signs the binary and writes the LaunchAgent
plist, then prints two manual steps that can't be automated:

1. Grant the compiled binary Accessibility permission in System Settings
   (macOS doesn't auto-prompt for bare CLI binaries with no app bundle —
   add it manually via "+", Cmd+Shift+G to type the path).
2. Run `launchctl bootstrap gui/$(id -u) <agent-plist-path>` yourself to
   load the LaunchAgent (`RunAtLoad` + `KeepAlive` means it then
   auto-starts on every future login/reboot without further action).

## Uninstall

```
launchctl bootout gui/$(id -u)/com.adamdurham.siripreempt
rm ~/Library/LaunchAgents/com.adamdurham.siripreempt.plist ~/bin/siri_preempt
```

Then remove the Accessibility entry manually in System Settings > Privacy
& Security > Accessibility.

## Caveats

- Depends on internal, undocumented Siri AI behavior (`com.apple.campo`
  bundle id, `hide`/`isActive`/`hidden` NSRunningApplication state) on a
  **beta** OS build. May need updating or may stop being necessary on a
  future macOS release if Apple changes this behavior or exposes a proper
  setting.
- If 1Password ever changes its bundle id or its Quick Access shortcut
  away from Cmd+Shift+Space, update the target combo / bundle id
  constants in `siri_preempt.m` accordingly.
