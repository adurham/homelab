/*
 * pam_yk.so — authenticate sudo only when the pinned YubiKey is present.
 *
 * Performs a real PC/SC challenge-response against a PIV slot 9A ECDSA P-256
 * key (not a USB presence check), then verifies the signature against a
 * compiled-in public key. No conversation calls, no PIN, no agents: the card
 * answers by itself because the slot uses PIN policy "never" and touch policy
 * "never".
 *
 * Key present  -> PAM_SUCCESS
 * Key absent   -> PAM_AUTH_ERR (caller pairs this with "requisite pam_deny")
 *
 * Build (arm64 requires the ad-hoc signature):
 *   clang -bundle -o pam_yk.so pam_yk.c \
 *         -framework PCSC -framework Security -framework CoreFoundation \
 *         -I/System/Library/Frameworks/PCSC.framework/Headers
 *   codesign -s - -f pam_yk.so
 */

#define _DARWIN_C_SOURCE 1
#include <security/pam_modules.h>
#include <security/pam_appl.h>
#include <PCSC/winscard.h>
#include <PCSC/wintypes.h>
#include <Security/Security.h>
#include <CoreFoundation/CoreFoundation.h>
#include <syslog.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <unistd.h>
#include <stdarg.h>

/* X9.63 uncompressed public key of PIV slot 9A (0x04 || X || Y). */
static const unsigned char PINNED_KEY[65] = {
    0x04, 0xc9, 0xa2, 0xfe, 0x7e, 0xd1, 0xd2, 0x43, 0x38, 0x75, 0xda, 0x3e, 0xe2, 0x54, 0xa4, 0x22,
    0xe3, 0xff, 0xcd, 0x63, 0x4b, 0x27, 0x49, 0x3a, 0x41, 0x46, 0xea, 0xc1, 0xfa, 0x38, 0xd2, 0x38,
    0x2d, 0x7f, 0xd5, 0xd7, 0x10, 0xde, 0x5b, 0x0e, 0x41, 0x94, 0xb0, 0x8b, 0x7f, 0xc0, 0x39, 0x44,
    0xae, 0x5c, 0x21, 0xa5, 0xbd, 0x66, 0x2c, 0x37, 0xd1, 0x6d, 0x52, 0x1b, 0x5a, 0x64, 0x95, 0x06,
    0x43,
};

static const unsigned char PIV_AID[] = { 0xA0, 0x00, 0x00, 0x03, 0x08 };

static int verify_sig(const unsigned char digest[32],
                      const unsigned char *sig, size_t siglen)
{
    int ok = 0;
    CFDataRef key_data = CFDataCreate(NULL, PINNED_KEY, sizeof(PINNED_KEY));
    if (!key_data) return 0;

    const void *attr_keys[] = { kSecAttrKeyType, kSecAttrKeyClass };
    const void *attr_vals[] = { kSecAttrKeyTypeECSECPrimeRandom, kSecAttrKeyClassPublic };
    CFDictionaryRef attrs = CFDictionaryCreate(NULL, attr_keys, attr_vals, 2,
                                               &kCFTypeDictionaryKeyCallBacks,
                                               &kCFTypeDictionaryValueCallBacks);
    SecKeyRef key = attrs ? SecKeyCreateWithData(key_data, attrs, NULL) : NULL;
    if (key) {
        CFDataRef d = CFDataCreate(NULL, digest, 32);
        CFDataRef s = CFDataCreate(NULL, sig, (CFIndex)siglen);
        if (d && s) {
            ok = SecKeyVerifySignature(key, kSecKeyAlgorithmECDSASignatureDigestX962SHA256,
                                       d, s, NULL) ? 1 : 0;
        }
        if (d) CFRelease(d);
        if (s) CFRelease(s);
        CFRelease(key);
    }
    if (attrs) CFRelease(attrs);
    CFRelease(key_data);
    return ok;
}

/* One attempt: return 1 on a verified challenge-response. */
#ifdef STANDALONE
#  define DBG(...) fprintf(stderr, __VA_ARGS__)
#else
#  define DBG(...) do { } while (0)
#endif

static int attempt(void)
{
    SCARDCONTEXT ctx = 0;
    SCARDHANDLE card = 0;
    DWORD proto = 0;
    char readers[1024];
    DWORD readers_len = sizeof(readers);
    int result = 0;
    unsigned char chal[32];
    unsigned char resp[512];
    DWORD resp_len;
    unsigned char apdu[48];

    long est = SCardEstablishContext(SCARD_SCOPE_USER, NULL, NULL, &ctx);
    if (est != SCARD_S_SUCCESS) {
        return 0;
    }

    if (SCardListReaders(ctx, NULL, readers, &readers_len) != SCARD_S_SUCCESS) {
        SCardReleaseContext(ctx);
        return 0;
    }

    const char *reader = NULL;
    for (const char *p = readers; *p; p += strlen(p) + 1) {
        if (strcasestr(p, "yubikey")) { reader = p; break; }
    }
    if (!reader) { SCardReleaseContext(ctx); return 0; }
    DBG("reader: %s\n", reader);

    long crv = SCardConnect(ctx, reader, SCARD_SHARE_SHARED,
                            SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1, &card, &proto);
    if (crv != SCARD_S_SUCCESS) {
        SCardReleaseContext(ctx);
        return 0;
    }
    DBG("connected, proto=0x%lx\n", (unsigned long)proto);

    /* SELECT the PIV application. */
    static const unsigned char select_piv[] =
        { 0x00, 0xA4, 0x04, 0x00, 0x05, 0xA0, 0x00, 0x00, 0x03, 0x08 };
    resp_len = sizeof(resp);
    long trv = SCardTransmit(card, SCARD_PCI_T1, select_piv, sizeof(select_piv),
                             NULL, resp, &resp_len);
    if (trv != SCARD_S_SUCCESS || resp_len < 2) {
        SCardDisconnect(card, SCARD_LEAVE_CARD);
        SCardReleaseContext(ctx);
        return 0;
    }
    DBG("select SW=%02x%02x\n", resp[resp_len-2], resp[resp_len-1]);

    /* GENERAL AUTHENTICATE, algorithm ECCP256 (0x11), slot 9A.
       Template: 7C 24 | 82 00 | 81 20 <32-byte challenge-as-digest> */
    arc4random_buf(chal, sizeof(chal));
    size_t i = 0;
    apdu[i++] = 0x00; apdu[i++] = 0x87; apdu[i++] = 0x11; apdu[i++] = 0x9A;
    apdu[i++] = 0x26;                       /* Lc = 38 */
    apdu[i++] = 0x7C; apdu[i++] = 0x24;     /* dynamic auth template */
    apdu[i++] = 0x82; apdu[i++] = 0x00;     /* empty response field */
    apdu[i++] = 0x81; apdu[i++] = 0x20;     /* challenge, 32 bytes */
    memcpy(apdu + i, chal, 32); i += 32;
    apdu[i++] = 0x00;                       /* Le */

    resp_len = sizeof(resp);
    long arv = SCardTransmit(card, SCARD_PCI_T1, apdu, i, NULL, resp, &resp_len);
    DBG("genauth rv=0x%08lx len=%lu first=%02x\n", (unsigned long)arv,
        (unsigned long)resp_len, resp_len ? resp[0] : 0);
    if (arv == SCARD_S_SUCCESS && resp_len > 4 && resp[0] == 0x7C) {
        size_t off = 2;
        size_t tmpl_len = resp[1];
        if (tmpl_len + 2 <= resp_len) {
            while (off + 1 < tmpl_len + 2) {
                unsigned char tag = resp[off];
                size_t len = resp[off + 1];
                off += 2;
                if (tag == 0x82 && off + len <= resp_len) {
                    result = verify_sig(chal, resp + off, len);
                    DBG("sig len=%zu verify=%d\n", len, result);
                    break;
                }
                off += len;
            }
        }
    }

    SCardDisconnect(card, SCARD_LEAVE_CARD);
    SCardReleaseContext(ctx);
    return result;
}

static int yk_auth(void)
{
    /* The card is briefly unavailable while ctkd / another PCSC client is
       attached (SCARD_E_READER_UNAVAILABLE) and right after wake. Retry a
       handful of times instead of failing the login. */
    for (int i = 0; i < 5; i++) {
        if (attempt()) return 1;
        usleep(200000);
    }
    return 0;
}

PAM_EXTERN int
pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char *argv[])
{
    int rc = yk_auth();
    if (rc) {
        syslog(LOG_AUTHPRIV | LOG_NOTICE, "pam_yk: YubiKey challenge-response OK");
        return PAM_SUCCESS;
    }
    syslog(LOG_AUTHPRIV | LOG_NOTICE, "pam_yk: YubiKey absent or signature failed");
    return PAM_AUTH_ERR;
}

PAM_EXTERN int
pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char *argv[])
{
    return PAM_SUCCESS;
}

#ifdef STANDALONE
int main(void)
{
    int rc = yk_auth();
    printf("pam_yk self-test: %s\n", rc ? "OK (signature verified)" : "FAIL");
    return rc ? 0 : 1;
}
#endif
