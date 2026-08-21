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
// bigger tradeoff than this workaround.
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
// receives the real event normally. A debounce guard (gPollInFlight)
// ensures only one poll/preempt cycle runs at a time -- without it,
// rapid or repeated presses would spawn multiple concurrent pollers each
// independently hiding Siri AI and re-activating 1Password, potentially
// fighting each other.
//
// On detecting the combo (and no poll already in flight), two mechanisms
// run to catch Siri AI becoming active and immediately hide it +
// re-activate 1Password:
//
//   1. An NSWorkspaceDidActivateApplicationNotification observer, in
//      case Siri AI ever posts one (belt-and-suspenders; see below for
//      why this alone is not sufficient).
//   2. A short bounded poll of NSRunningApplication.isActive/.hidden for
//      Siri AI (com.apple.campo), checked every 0.5ms for up to ~200ms
//      immediately after the keydown.
//
// Why is (2) necessary when (1) exists? Measured directly: Siri AI has
// NSApplicationActivationPolicy = 1 (accessory app -- like a menu-bar
// helper, not a regular Dock app). A 30-second passive watch, sampling
// isActive/hidden every 5ms while repeatedly triggering the combo, never
// observed either property change, and NSWorkspaceDidActivateApplication
// notification never fired for com.apple.campo either -- yet the panel
// visibly appeared and dismissed 1Password every time. An
// NSWorkspaceDidActivateApplicationNotification-only version (no polling)
// was built, deployed, and tested live -- it did not work.
//
// IMPORTANT CAVEAT ON THE POLL PREDICATE: direct measurement of Siri AI's
// steady-state (not-visibly-active) NSRunningApplication state showed
// isActive=0, hidden=0 -- meaning `!hidden` is true even when Siri AI is
// NOT visibly presenting its panel. This means the poll loop's exit
// condition (siriAI.isActive || !siriAI.hidden) is very likely satisfied
// on the very first iteration on every trigger, not only once Siri AI
// actually becomes visible. In effect this loop currently behaves close
// to "on combo detected, immediately hide Siri AI + reactivate
// 1Password" rather than "wait for Siri AI to actually appear, then
// react" -- diagnostic logging of which iteration fires
// (`fired at iteration %d`) is left in place; if production logs
// consistently show iteration 0, the loop is providing no actual waiting
// behavior and could be replaced with a single immediate call. It is
// being kept as a bounded retry specifically for defense-in-depth (in
// case the steady-state reading was a snapshot artifact and Siri AI's
// window presentation is occasionally slower), not removed outright,
// since removing it changes behavior that was confirmed working live and
// has not been independently re-verified with the immediate-only version.
//
// Why not just disable Siri? `defaults write com.apple.assistant.support
// "Assistant Enabled" -bool false` works and is a one-line revert, but it
// kills Siri entirely rather than just freeing up this one hotkey combo.
//
// Why not just change 1Password's Quick Access shortcut to something
// else? Explicitly considered and rejected -- the requirement is to keep
// using Cmd+Shift+Space for 1Password specifically.
//
// Why not a blocking (active) CGEventTap that swallows the keystroke?
// Tested and rejected: also silently killed 1Password's own response to
// the same combo -- both apps are independent listeners on the same raw
// key event, a blocking tap can't discriminate between them.
//
// Why not poll CGWindowListCopyWindowInfo unconditionally (not scoped to
// right after a keypress)? Tested and rejected: too slow at a
// sustainable poll interval (~15ms) -- 1Password already lost focus by
// the time such a loop noticed the window.
//
// Known limitations (documented, not silently ignored):
// - Uses `[onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps]`,
//   which is deprecated (macOS 14+). The modern replacement,
//   `-activateFromApplication:options:`, was tried and tested live -- it
//   did NOT work (Siri AI's panel still won the focus race with it), so
//   the deprecated call is kept because it is the one actually confirmed
//   to work repeatedly. macOS's cooperative activation model means even
//   this proven call could stop working on some future build. If
//   1Password stops regaining focus after a macOS update, this is the
//   first place to look -- but re-test any replacement API live before
//   swapping it in; it is not a given that the "correct"/modern API
//   actually behaves the same way for this specific undocumented
//   accessory-app scenario.
// - Event taps receive no events while SecureEventInput is engaged (e.g.
//   focus is in a password field). Pressing the combo in a secure field
//   is invisible to this tool.
// - If the Input Monitoring TCC grant is ever revoked (e.g. after a
//   rebuild changes the app's signature), CGEventTapCreate returns NULL
//   and the process exits with status 1. Combined with the LaunchAgent's
//   KeepAlive=true, this becomes a silent respawn loop until the
//   permission is re-granted. Check `tail -f /tmp/siri_preempt.log` if
//   the fix silently stops working.
// - `preemptSiriAI()` re-activates 1Password the *app*, not specifically
//   its Quick Access panel. If Quick Access has already fully dismissed
//   itself by the time this runs, activating 1Password may just front
//   its main window rather than reopen Quick Access. Confirmed live that
//   the panel stays open and usable with the current timing, but if
//   Siri AI's activation timing shifts on a future build such that the
//   panel fully dismisses before this fires, this may need to instead
//   re-post 1Password's own hotkey via CGEventPost rather than just
//   activating the app.
//
// This is a workaround for **beta OS** behavior. Re-evaluate on the next
// macOS build. Consider filing Feedback (feedbackassistant.apple.com)
// about the undocumented, non-configurable hotkey interception.
//
// Build:
//   clang -O2 -fobjc-arc -o siri_preempt siri_preempt.m -framework Cocoa -framework ApplicationServices
//   codesign -s - siri_preempt
//
// Requires: the compiled binary (packaged as a .app bundle -- see
// install.sh and the README's ".app bundle vs bare binary" section for
// why a bare CLI binary reliably fails CGEventTapCreate when spawned by
// launchd) must be added to System Settings -> Privacy & Security ->
// Input Monitoring (NOT Accessibility -- a listen-only keyboard tap only
// needs kTCCServiceListenEvent).

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <stdatomic.h>

static NSString * const kSiriAIBundleID = @"com.apple.campo";
static NSString * const k1PasswordBundleID = @"com.1password.1password";

// How long to poll for Siri AI becoming active after detecting the
// triggering keypress. See file header re: the poll predicate likely
// being satisfied on iteration 0 -- kept as bounded defense-in-depth.
static const int POLL_STEPS = 400;          // 400 * 0.5ms = ~200ms
static const useconds_t POLL_INTERVAL_US = 500; // 0.5ms

// The tap, stashed globally so the callback can re-enable it if the OS
// disables it (timeout / user input).
static CFMachPortRef gTap = NULL;

// Debounce guard: only one poll/preempt cycle runs at a time. Without
// this, rapid or repeated combo presses would spawn multiple concurrent
// pollers, each independently calling hide/activate and potentially
// fighting each other (e.g. re-activating 1Password again after the user
// has already moved on to something else).
static _Atomic bool gPollInFlight = false;

static void preemptSiriAI(int firedAtIteration) {
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
            // NOTE: -activateFromApplication:options: (macOS 14+) was
            // tried here as the modern replacement for the deprecated
            // activateWithOptions:NSApplicationActivateIgnoringOtherApps
            // call, on paper it's the more "correct" API. It was tested
            // live and did NOT work -- Siri AI's panel still won the
            // focus race with that call. Reverted to the deprecated call
            // because it is the one actually confirmed, repeatedly, to
            // work. If Apple's activation behavior changes again, this
            // is the first place to look, but don't swap this for
            // activateFromApplication: again without live-testing it.
            [onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps];
        }
        NSLog(@"siri_preempt: hid Siri AI + reactivated 1Password (fired at iteration %d)", firedAtIteration);
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
            bool expected = false;
            if (atomic_compare_exchange_strong(&gPollInFlight, &expected, true)) {
                preemptSiriAI(-1);
                atomic_store(&gPollInFlight, false);
            }
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
        // Debounce: if a poll is already running (e.g. from a very rapid
        // repeated press that somehow isn't caught by the autorepeat
        // filter above, or two presses close together), don't start a
        // second concurrent poller.
        bool expected = false;
        if (!atomic_compare_exchange_strong(&gPollInFlight, &expected, true)) {
            NSLog(@"siri_preempt: combo detected but a poll is already in flight, skipping");
            return event;
        }

        NSLog(@"siri_preempt: combo detected, polling for Siri AI activation");
        // Dispatched to a background queue, NOT the main queue: the poll
        // sleeps for up to ~200ms, and the main queue/run loop is what
        // delivers further CGEventTap callbacks and NSWorkspace
        // notifications. Blocking main here would stall event delivery
        // for the whole poll duration on every trigger.
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0), ^{
            @autoreleasepool {
                // Cache the NSRunningApplication reference once instead
                // of re-querying Launch Services on every poll iteration
                // (which is the actual cost of a 0.5ms-interval loop --
                // the sleep itself is cheap, repeated LS lookups are
                // not).
                NSArray<NSRunningApplication *> *siriApps =
                    [NSRunningApplication runningApplicationsWithBundleIdentifier:kSiriAIBundleID];
                NSRunningApplication *siriAI = siriApps.firstObject;

                BOOL fired = NO;
                for (int i = 0; i < POLL_STEPS; i++) {
                    if (siriAI && (siriAI.isActive || !siriAI.hidden)) {
                        preemptSiriAI(i);
                        fired = YES;
                        break;
                    }
                    usleep(POLL_INTERVAL_US);
                }
                if (!fired) {
                    NSLog(@"siri_preempt: poll window expired without detecting Siri AI activation");
                }
                atomic_store(&gPollInFlight, false);
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
