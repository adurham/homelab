#!/bin/bash
# Build, verify, then install pam_yk.so. Refuses to install a module that has
# not just authenticated the attached YubiKey.
#
# Why this exists: installing an unverified build into /etc/pam.d/sudo_local
# bricks sudo for the whole machine (the stack is `sufficient pam_yk` +
# `required pam_deny`, so a failing module means no password fallback either).
set -euo pipefail
cd "$(dirname "$0")"

CC=${CC:-clang}
FRAMEWORKS=(-framework PCSC -framework Security -framework CoreFoundation)
INC=(-I/System/Library/Frameworks/PCSC.framework/Headers)

echo "== build (do NOT codesign: AMFI rejects non-linker signatures) =="
rm -f pam_yk.so
$CC -bundle -o pam_yk.so pam_yk.c "${FRAMEWORKS[@]}" "${INC[@]}"
# The linker's ad-hoc signature is the one sudo will accept. codesign -s - -f
# replaces it with a plain adhoc signature that amfid rejects with -423.

echo "== sign flags =="
codesign -dv --verbose=2 pam_yk.so 2>&1 | grep -o 'flags=0x[0-9a-f]*(.*)' || true

echo "== harness: module must authenticate the card in front of us =="
tmp_h=$(mktemp /tmp/pam_yk_harness.XXXXXX.c)
tmp_b=${tmp_h%.c}
cat > "$tmp_h" <<'EOF'
#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
    void *h = dlopen(argv[1], RTLD_NOW);
    if (!h) { printf("dlopen failed: %s\n", dlerror()); return 2; }
    int (*fn)(void*, int, int, const char**) = dlsym(h, "pam_sm_authenticate");
    if (!fn) { printf("no symbol\n"); return 3; }
    int rc = fn(NULL, 0, 0, NULL);
    printf("pam_sm_authenticate -> %d (0 = success)\n", rc);
    return rc;
}
EOF
clang -o "$tmp_b" "$tmp_h"
if ! "$tmp_b" "$PWD/pam_yk.so"; then
    echo "REFUSING TO INSTALL: module did not authenticate the attached key." >&2
    rm -f "$tmp_h" "$tmp_b"
    exit 1
fi
rm -f "$tmp_h" "$tmp_b"

echo "== install =="
sudo install -o root -g wheel -m 0755 "$PWD/pam_yk.so" /usr/local/lib/pam/pam_yk.so
echo "== post-install check =="
sudo -k
if sudo true; then
    echo "OK: sudo authenticates with the key present"
else
    echo "FAILED: sudo did not authenticate. Restoring previous binary is required." >&2
    exit 1
fi
