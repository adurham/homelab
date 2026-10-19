#include <PCSC/winscard.h>
#include <PCSC/wintypes.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    SCARDCONTEXT ctx = 0;
    long rv = SCardEstablishContext(SCARD_SCOPE_USER, NULL, NULL, &ctx);
    printf("establish: 0x%08lx\n", (unsigned long)rv);
    if (rv) return 1;

    char readers[1024];
    DWORD len = sizeof(readers);
    rv = SCardListReaders(ctx, NULL, readers, &len);
    printf("list: 0x%08lx len=%lu\n", (unsigned long)rv, (unsigned long)len);
    for (char *p = readers; *p; p += strlen(p) + 1) printf("  reader: %s\n", p);

    struct { const char *name; DWORD share; DWORD proto; } tries[] = {
        {"shared T0|T1", SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1},
        {"shared T1",    SCARD_SHARE_SHARED, SCARD_PROTOCOL_T1},
        {"shared T0",    SCARD_SHARE_SHARED, SCARD_PROTOCOL_T0},
        {"shared ANY",   SCARD_SHARE_SHARED, SCARD_PROTOCOL_ANY},
        {"direct T1",    SCARD_SHARE_DIRECT, SCARD_PROTOCOL_T1},
    };
    for (unsigned i = 0; i < sizeof(tries)/sizeof(tries[0]); i++) {
        SCARDHANDLE card = 0; DWORD proto = 0;
        long r = SCardConnect(ctx, readers, tries[i].share, tries[i].proto, &card, &proto);
        printf("%-14s rv=0x%08lx activeproto=0x%lx\n", tries[i].name, (unsigned long)r, (unsigned long)proto);
        if (r == 0) SCardDisconnect(card, SCARD_LEAVE_CARD);
    }
    SCardReleaseContext(ctx);
    return 0;
}
