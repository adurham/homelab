// siri_preempt.m
//
// Problem: on macOS 27 (Tahoe/beta "27.0", build 26A5416b), the new merged
// Spotlight/Siri app ("Siri AI.app", bundle id com.apple.campo) intercepts
// Cmd+Shift+Space as an internal invocation gesture. This combo is not
// configurable anywhere in the classic Siri/Spotlight preference domains
// (com.apple.Siri, com.apple.assistant*, com.apple.symbolichotkeys.plist,
// com.apple.Spotlight, com.apple.campo itself -- checked via `defaults read`
// and `defaults find campo`) -- it's hardcoded in the new Campo/Siri AI
// binary with no exposed defaults(1) toggle as of this build.
//
// Also confirmed: `launchctl bootout gui/$(id -u)/com.apple.campo` fails
// with "Operation not permitted while System Integrity Protection is
// engaged" -- Apple's campo LaunchAgent is SIP-protected and cannot be
// unloaded/disabled without disabling SIP system-wide, which is a much
// bigger tradeoff than this workaround. So there is no way to simply turn
// Siri AI off for this hotkey without either disabling SIP or disabling
// Siri/Assistant entirely (see rejected approach below).
//
// This collides with 1Password's Quick Access global shortcut, which is
// also bound to Cmd+Shift+Space: pressing it opens 1Password's quick bar,
// then Siri AI steals focus a beat later and 1Password's panel
// self-dismisses because it lost key-window status.
//
// Fix: a low-level listen-only CGEventTap watches for the exact Cmd+Shift+
// Space combo (masking out irrelevant modifier bits like caps lock, and
// ignoring key-repeat events from a held-down combo). It NEVER blocks/
// consumes the keystroke -- every app, including 1Password, still
// receives the real event normally.
//
// On detecting the combo, two mechanisms run concurrently to catch Siri
// AI becoming active and immediately hide it + re-activate 1Password:
//
//   1. An NSWorkspaceDidActivateApplicationNotification observer, in
//      case Siri AI ever posts one (belt-and-suspenders; see below for
//      why this alone is not sufficient).
//   2. A tight busy-poll of NSRunningApplication.isActive/.hidden for
//      Siri AI (com.apple.campo), checked every 0.5ms for up to ~200ms
//      immediately after the keydown.
//
// Why is (2) necessary when (1) exists? Measured directly: Siri AI has
// NSApplicationActivationPolicy = 1 (accessory app -- like a menu-bar
// helper, not a regular Dock app). A 30-second passive watch, sampling
// isActive/hidden every 5ms while repeatedly triggering the combo, never
// observed either property change, and NSWorkspaceDidActivateApplication
// notification never fired for com.apple.campo either -- yet the panel
// visibly appeared and dismissed 1Password every time. Conclusion: this
// accessory app's activation is either not reflected in the standard
// NSRunningApplication/NSWorkspace observation surface at all, or the
// state change is real but so brief (sub-5ms) that passive sampling at
// normal intervals cannot reliably observe it. Only the *original*
// implementation of this tool -- a tight 0.5ms busy-poll running
// immediately after each keydown, for a bounded ~200ms window -- was
// ever confirmed (live, repeatedly) to catch and react to it. So this is
// not "the wrong tool used out of laziness"; it's the only mechanism
// that has actually been observed to work for this specific undocumented
// accessory-app activation. The poll only runs for ~200ms after a
// detected combo press, not continuously, so steady-state CPU is still
// ~0%.
//
// Why not just disable Siri? `defaults write com.apple.assistant.support
// "Assistant Enabled" -bool false` works and is a one-line revert, but it
// kills Siri entirely rather than just freeing up this one hotkey combo.
// This tool keeps Siri fully functional everywhere else.
//
// Why not just change 1Password's Quick Access shortcut to something
// else? That is the objectively simplest fix, and was explicitly
// considered and rejected -- the user wants to keep using Cmd+Shift+Space
// for 1Password specifically and have Siri AI stay out of the way,
// not remap 1Password around Siri AI's undocumented behavior.
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
// CGWindowListCopyWindowInfo, unconditionally, not just right after a
// keypress)? Tested and rejected: too slow at a sustainable poll interval
// (~15ms). By the time such a loop notices the window on screen,
// 1Password has already lost focus and self-dismissed. Polling only
// makes sense scoped tightly to the ~200ms right after the triggering
// keypress, which is what this tool does.
//
// Known limitations (documented, not silently ignored):
// - `[onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps]`
//   is deprecated (macOS 14+) and macOS's cooperative activation model
//   means a background process's request to activate another app may
//   simply be ignored on some future build. This is the most fragile
//   part of the whole approach -- if 1Password stops regaining focus
//   after a macOS update, this is the first place to look.
// - Event taps receive no events while SecureEventInput is engaged (e.g.
//   focus is in a password field). If you press the combo in a secure
//   field, this tool cannot see or react to it.
// - If the underlying Input Monitoring TCC grant is ever revoked (e.g.
//   after a rebuild changes the binary's cdhash, since it's ad-hoc
//   signed), CGEventTapCreate returns NULL and the process exits with
//   status 1. Combined with the LaunchAgent's KeepAlive=true, this
//   becomes a silent respawn loop (no protection, no crash visible to
//   the user) until the permission is re-granted. Check
//   `tail -f /tmp/siri_preempt.log` if the fix silently stops working.
// - The ~200ms busy-poll window briefly uses more CPU than idle (still a
//   single core, short bursts, negligible in practice) -- documented
//   here rather than silently claimed to be "zero cost always".
//
// This is a workaround for **beta OS** behavior. Re-evaluate on the next
// macOS build -- Apple may change Siri AI's activation behavior or expose
// a real setting, which would make this whole tool unnecessary. Consider
// filing Feedback (feedbackassistant.apple.com) about the undocumented,
// non-configurable hotkey interception.
//
// Build:
//   clang -O2 -fobjc-arc -o siri_preempt siri_preempt.m -framework Cocoa -framework ApplicationServices
//   codesign -s - siri_preempt
//
// Requires: the compiled binary must be added to System Settings ->
// Privacy & Security -> Input Monitoring (NOT Accessibility -- a
// listen-only keyboard tap only needs kTCCServiceListenEvent; Accessibility
// grants strictly more, including synthetic-event posting and UI control,
// which this tool does not use and should not request). macOS does not
// auto-prompt for bare CLI binaries with no app bundle -- add it manually
// via the "+" button, Cmd+Shift+G to type the path directly.
//
// See install.sh in this directory for the full setup (compile, sign,
// LaunchAgent registration).

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

static NSString * const kSiriAIBundleID = @"com.apple.campo";
static NSString * const k1PasswordBundleID = @"com.1password.1password";

// How long to busy-poll for Siri AI becoming active after detecting the
// triggering keypress. Measured Siri AI activation happens well under
// 100ms after the key event in testing; 200ms gives comfortable margin.
static const int POLL_STEPS = 400;          // 400 * 0.5ms = ~200ms
static const useconds_t POLL_INTERVAL_US = 500; // 0.5ms

// The tap, stashed globally so the callback can re-enable it if the OS
// disables it (timeout / user input). CGEventTapCreate's refcon parameter
// can't be pre-populated with the tap's own reference before it exists,
// so a global is simpler and correct than a two-pass create/recreate.
static CFMachPortRef gTap = NULL;

static void preemptSiriAI(void) {
    @autoreleasepool {
        NSArray<NSRunningApplication *> *siriApps =
            [NSRunningApplication runningApplicationsWithBundleIdentifier:kSiriAIBundleID];
        NSRunningApplication *siriAI = siriApps.firstObject;
        if (!siriAI) return;

        NSArray<NSRunningApplication *> *onePassApps =
            [NSRunningApplication runningApplicationsWithBundleIdentifier:k1PasswordBundleID];
        NSRunningApplication *onePass = onePassApps.firstObject;

        [siriAI hide];
        if (onePass) {
            // Deprecated but still functional as of this build; see the
            // "Known limitations" note in the file header for why this
            // could stop working on a future macOS release.
            [onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps];
        }
        NSLog(@"siri_preempt: hid Siri AI + reactivated 1Password");
    }
}

// Belt-and-suspenders: react instantly if Siri AI ever does post a
// standard activation notification (not observed in testing, but cheap
// to keep in case behavior differs on other builds/configurations).
static void installActivationObserver(void) {
    [[[NSWorkspace sharedWorkspace] notificationCenter]
        addObserverForName:NSWorkspaceDidActivateApplicationNotification
                    object:nil
                     queue:[NSOperationQueue mainQueue]
                usingBlock:^(NSNotification *note) {
        NSRunningApplication *app = note.userInfo[NSWorkspaceApplicationKey];
        if ([app.bundleIdentifier isEqualToString:kSiriAIBundleID]) {
            NSLog(@"siri_preempt: got activation notification for Siri AI (unexpected but handled)");
            preemptSiriAI();
        }
    }];
}

CGEventRef keyTapCallback(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void *refcon) {
    // Re-enable the tap if the OS disabled it (e.g. after a timeout under
    // heavy load, or user input while a modal was up). Without this, the
    // tap can silently stop delivering events and this tool goes dark
    // with no crash and no obvious symptom other than "stopped working".
    if (type == kCGEventTapDisabledByTimeout || type == kCGEventTapDisabledByUserInput) {
        if (gTap) {
            CGEventTapEnable(gTap, true);
            NSLog(@"siri_preempt: tap was disabled (type=%d), re-enabled", (int)type);
        }
        return event;
    }

    if (type != kCGEventKeyDown) return event;

    // Ignore key-repeat: holding the combo down would otherwise re-arm
    // and re-poll on every autorepeat tick with no benefit.
    if (CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat)) {
        return event;
    }

    CGEventFlags flags = CGEventGetFlags(event);
    int64_t keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);

    // Space bar (49) with EXACTLY Cmd+Shift held (no Option/Control).
    // Mask out irrelevant flag bits (caps lock, numpad, function, etc.)
    // before comparing.
    CGEventFlags relevant = flags & (kCGEventFlagMaskCommand | kCGEventFlagMaskShift |
                                       kCGEventFlagMaskAlternate | kCGEventFlagMaskControl);
    CGEventFlags target = kCGEventFlagMaskCommand | kCGEventFlagMaskShift;

    if (keycode == 49 && relevant == target) {
        NSLog(@"siri_preempt: combo detected, polling for Siri AI activation");
        // Dispatched to a background queue, NOT the main queue: the poll
        // sleeps for up to ~200ms, and the main queue/run loop is what
        // delivers further CGEventTap callbacks and NSWorkspace
        // notifications. Blocking main here would stall event delivery
        // for the whole poll duration on every trigger. The actual
        // hide/activate calls in preemptSiriAI() happen after the poll
        // finds a match; NSRunningApplication/NSWorkspace calls are safe
        // to invoke off the main thread for these read-only + control
        // operations (no UI is being drawn by this process).
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0), ^{
            @autoreleasepool {
                for (int i = 0; i < POLL_STEPS; i++) {
                    NSArray<NSRunningApplication *> *siriApps =
                        [NSRunningApplication runningApplicationsWithBundleIdentifier:kSiriAIBundleID];
                    NSRunningApplication *siriAI = siriApps.firstObject;
                    if (siriAI && (siriAI.isActive || !siriAI.hidden)) {
                        preemptSiriAI();
                        return;
                    }
                    usleep(POLL_INTERVAL_US);
                }
            }
        });
    }
    return event;
}

int main() {
    @autoreleasepool {
        // Listen-only: never blocks/consumes the keystroke. Every app,
        // including 1Password, still receives the real event normally.
        gTap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            CGEventMaskBit(kCGEventKeyDown),
            keyTapCallback,
            NULL
        );
        if (!gTap) {
            fprintf(stderr, "FAILED to create event tap - grant Input Monitoring permission to this binary in System Settings > Privacy & Security > Input Monitoring\n");
            return 1;
        }

        CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(NULL, gTap, 0);
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
        CGEventTapEnable(gTap, true);

        installActivationObserver();

        NSLog(@"siri_preempt: started, watching for Cmd+Shift+Space");
        CFRunLoopRun();
    }
    return 0;
}
