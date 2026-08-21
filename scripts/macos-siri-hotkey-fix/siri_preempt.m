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
// still receives the real event normally. Detecting the combo "arms" a
// short window (ARM_WINDOW_SEC). Separately, an NSWorkspace
// didActivateApplicationNotification observer watches for Siri AI
// (com.apple.campo) becoming the active app; if that happens while armed,
// it immediately hides Siri AI and re-activates 1Password. This is
// event-driven on both ends (key event -> arm, activation notification ->
// react) rather than a busy-poll loop, so it reacts as fast as the OS
// posts the activation notification instead of racing a fixed-step timer.
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
// already lost focus and self-dismissed.
//
// Why not the original fixed-step busy-poll race (0.5ms steps for up to
// 200ms after the keydown, checking isActive/hidden)? It worked in live
// testing but is a brute-force timing race, not a real fix: it burns CPU
// during the poll window and has no guarantee of winning if Siri AI's
// activation is ever slower/faster on a different build or under load.
// Replaced with the NSWorkspace-notification-driven version below, which
// reacts directly to the actual activation event instead of guessing a
// timing window.
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
#import <stdatomic.h>

static NSString * const kSiriAIBundleID = @"com.apple.campo";
static NSString * const k1PasswordBundleID = @"com.1password.1password";

// How long after detecting the Cmd+Shift+Space keydown we treat a
// subsequent Siri AI activation as "caused by that keypress" and react to
// it. Siri AI's actual activation happens well under 100ms after the key
// event in testing; 500ms gives comfortable margin without risking
// interference with a genuine, unrelated later launch of Siri AI.
static const double ARM_WINDOW_SEC = 0.5;

// Timestamp (CFAbsoluteTime) of the most recent matching keydown, or 0 if
// none seen yet / window has definitely expired. Accessed from both the
// CGEventTap callback thread and the main-thread notification handler,
// so it's a plain atomic double via a lock-free store/load pattern
// (values are monotonically increasing wall-clock times; a torn read is
// not a correctness concern here, only used for a coarse time-window
// check).
static _Atomic double gArmedUntil = 0;

static void preemptSiriAI(void) {
    NSArray<NSRunningApplication *> *siriApps =
        [NSRunningApplication runningApplicationsWithBundleIdentifier:kSiriAIBundleID];
    NSRunningApplication *siriAI = siriApps.firstObject;
    if (!siriAI) return;

    NSArray<NSRunningApplication *> *onePassApps =
        [NSRunningApplication runningApplicationsWithBundleIdentifier:k1PasswordBundleID];
    NSRunningApplication *onePass = onePassApps.firstObject;

    [siriAI hide];
    if (onePass) {
        [onePass activateWithOptions:NSApplicationActivateIgnoringOtherApps];
    }
    NSLog(@"siri_preempt: hid Siri AI + reactivated 1Password (notification-driven)");
}

CGEventRef keyTapCallback(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void *refcon) {
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
        double now = CFAbsoluteTimeGetCurrent();
        atomic_store(&gArmedUntil, now + ARM_WINDOW_SEC);
        NSLog(@"siri_preempt: combo detected, armed for %.0fms", ARM_WINDOW_SEC * 1000);

        // Cover the (rare, but possible) case where Siri AI is already
        // active/visible by the time we process this event -- don't rely
        // solely on the activation notification firing after us.
        NSArray<NSRunningApplication *> *siriApps =
            [NSRunningApplication runningApplicationsWithBundleIdentifier:kSiriAIBundleID];
        NSRunningApplication *siriAI = siriApps.firstObject;
        if (siriAI && (siriAI.isActive || !siriAI.hidden)) {
            dispatch_async(dispatch_get_main_queue(), ^{
                preemptSiriAI();
            });
        }
    }
    return event;
}

int main() {
    @autoreleasepool {
        // Listen-only: never blocks/consumes the keystroke. Every app,
        // including 1Password, still receives the real event normally.
        CFMachPortRef tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            CGEventMaskBit(kCGEventKeyDown),
            keyTapCallback,
            NULL
        );
        if (!tap) {
            fprintf(stderr, "FAILED to create event tap - grant Accessibility permission to this binary in System Settings > Privacy & Security > Accessibility\n");
            return 1;
        }
        CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(NULL, tap, 0);
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
        CGEventTapEnable(tap, true);

        // React the instant macOS actually activates Siri AI, instead of
        // guessing a timing window with a busy-poll loop.
        [[[NSWorkspace sharedWorkspace] notificationCenter]
            addObserverForName:NSWorkspaceDidActivateApplicationNotification
                        object:nil
                         queue:[NSOperationQueue mainQueue]
                    usingBlock:^(NSNotification *note) {
            NSRunningApplication *app = note.userInfo[NSWorkspaceApplicationKey];
            if (![app.bundleIdentifier isEqualToString:kSiriAIBundleID]) return;

            double armedUntil = atomic_load(&gArmedUntil);
            double now = CFAbsoluteTimeGetCurrent();
            if (now <= armedUntil) {
                preemptSiriAI();
            }
        }];

        NSLog(@"siri_preempt: started, watching for Cmd+Shift+Space (notification-driven)");
        CFRunLoopRun();
    }
    return 0;
}
