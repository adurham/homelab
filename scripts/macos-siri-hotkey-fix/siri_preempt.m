// siri_preempt.m
//
// Problem: on macOS 27 (Tahoe/beta "27.0", build 26A5416b), the new merged
// Spotlight/Siri app ("Siri AI.app", bundle id com.apple.campo) intercepts
// Cmd+Shift+Space as an internal invocation gesture. This combo is not
// configurable anywhere in the classic Siri/Spotlight preference domains
// (com.apple.Siri, com.apple.assistant*, com.apple.symbolichotkeys.plist,
// com.apple.Spotlight) -- it's hardcoded in the new Campo/Siri AI binary
// with no exposed defaults(1) toggle as of this build.
//
// This collides with 1Password's Quick Access global shortcut, which is
// also bound to Cmd+Shift+Space: pressing it opens 1Password's quick bar,
// then Siri AI steals focus a beat later and 1Password's panel
// self-dismisses because it lost key-window status.
//
// Fix: a low-level listen-only CGEventTap watches for the exact Cmd+Shift+
// Space combo (masking out irrelevant modifier bits like caps lock). It
// NEVER blocks/consumes the keystroke -- every app, including 1Password,
// still receives the real event normally. The instant the combo is seen,
// it races (0.5ms poll steps, up to ~200ms) to hide Siri AI's window and
// re-activate 1Password, winning the focus race before 1Password's panel
// has a chance to dismiss itself.
//
// Why not just disable Siri? `defaults write com.apple.assistant.support
// "Assistant Enabled" -bool false` works and is a one-line revert, but it
// kills Siri entirely rather than just freeing up this one hotkey combo.
// This tool keeps Siri fully functional everywhere else.
//
// Why not a blocking (active) CGEventTap that swallows the keystroke?
// Tested and rejected: 1Password and Siri AI are both independent global
// hotkey listeners reacting to the same raw OS keystroke, not fighting
// over "ownership" of a single registration. A tap that swallows the
// event blocks BOTH apps from ever seeing it -- there's no way to signal
// "let 1Password have this one, but not Siri" at the raw-key layer. So
// this must be listen-only, reacting after the fact instead.
//
// Why not just watch for Siri AI's window appearing and hide it (polling
// CGWindowListCopyWindowInfo)? Tested and rejected: too slow. By the time
// a ~15ms poll loop notices Siri AI's window on screen, 1Password has
// already lost focus and self-dismissed. Reacting to the keystroke itself
// (via the event tap) fires essentially instantly, well before Siri AI's
// window can steal focus.
//
// Build:
//   clang -O2 -o siri_preempt siri_preempt.m -framework Cocoa -framework ApplicationServices
//   codesign -s - siri_preempt
//
// Requires: the compiled binary must be added to System Settings ->
// Privacy & Security -> Accessibility (macOS does not auto-prompt for
// bare CLI binaries with no app bundle -- add it manually via the "+"
// button, Cmd+Shift+G to type the path directly).
//
// See install.sh in this directory for the full setup (compile, sign,
// LaunchAgent registration).

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

CGEventRef callback(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void *refcon) {
    if (type != kCGEventKeyDown) return event;

    CGEventFlags flags = CGEventGetFlags(event);
    int64_t keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);

    // Space bar (49) with EXACTLY Cmd+Shift held (no Option/Control).
    // Mask out irrelevant flag bits (caps lock, numpad, function, etc.)
    // before comparing.
    CGEventFlags relevant = flags & (kCGEventFlagMaskCommand | kCGEventFlagMaskShift |
                                       kCGEventFlagMaskAlternate | kCGEventFlagMaskControl);
    CGEventFlags target = kCGEventFlagMaskCommand | kCGEventFlagMaskShift;

    if (keycode == 49 && relevant == target) {
        NSLog(@"siri_preempt: combo detected");
        // Hide Siri AI repeatedly and re-activate 1Password repeatedly for a
        // short window, since we may need to win a focus race, not just a
        // single hide.
        NSArray<NSRunningApplication *> *onePassApps = [NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.1password.1password"];
        NSRunningApplication *onePass = onePassApps.firstObject;

        for (int i = 0; i < 400; i++) { // up to ~200ms @ 0.5ms steps
            NSArray<NSRunningApplication *> *siriApps = [NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.apple.campo"];
            NSRunningApplication *siriAI = siriApps.firstObject;
            if (siriAI && (siriAI.isActive || !siriAI.hidden)) {
                [siriAI hide];
                if (onePass) {
                    [onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps];
                }
                NSLog(@"siri_preempt: hid Siri + reactivated 1Password at check %d", i);
            }
            usleep(500);
        }
        NSLog(@"siri_preempt: race window done");
    }
    return event;
}

int main() {
    @autoreleasepool {
        CFMachPortRef tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            CGEventMaskBit(kCGEventKeyDown),
            callback,
            NULL
        );
        if (!tap) {
            fprintf(stderr, "FAILED to create event tap - grant Accessibility permission to this binary in System Settings > Privacy & Security > Accessibility\n");
            return 1;
        }
        CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(NULL, tap, 0);
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
        CGEventTapEnable(tap, true);
        NSLog(@"siri_preempt: started, watching for Cmd+Shift+Space");
        CFRunLoopRun();
    }
    return 0;
}
