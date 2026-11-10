# Recovering a parked media download

When a collector cannot push a download to the gallery, it does **not** keep the
file: staging is a tmpfs so that plaintext media never lands on persistent
storage, and parked files are therefore written **encrypted to a public key**.

The matching private key is deliberately not on any lab host — it lives in the
password manager (item: *media-ingest park key (gpg private)*, Hermes vault).
A compromised box yields ciphertext only.

## Where parked files live

| Host | Directory | Written by |
|---|---|---|
| media-ingest-01 | `/var/lib/media-ingest/failed/` | `collector.py`, `reconcile.py` |
| media-ingest-02 | `/var/lib/media-ingest-02/failed/` | `scraper_wrapper.py` |

Each item is `<stem><ext>.gpg` plus a `<stem>.json` sidecar holding the target
`folder` and `date`. The gallery sweep on media-ingest-01 cannot decrypt these
(by design) — it logs a count of items awaiting manual recovery.

## Recovery (run from the workstation)

1. Pull the private key out of the password manager through the bridge:

   ```sh
   op-bridge-rpc item get "<item id>" --format json | jq -r '.fields[] | select(.label=="notesPlain") | .value' > /tmp/park.key
   export GNUPGHOME=$(mktemp -d); chmod 700 "$GNUPGHOME"
   gpg --batch --quiet --import /tmp/park.key
   ```

2. Copy the parked pair back and decrypt it:

   ```sh
   scp -i ~/.ssh/id_ansible amd@media-ingest-01:/var/lib/media-ingest/failed/<stem>.gpg ./
   gpg --batch --quiet --decrypt <stem>.gpg > <stem>
   sha256sum <stem>        # sanity check against the sidecar size, if recorded
   ```

3. Push it into the gallery under the stem the sidecar names (folder + date), as
   if the original capture had succeeded.

4. Clean up: delete the decrypted copy and `rm -rf "$GNUPGHOME" /tmp/park.key`.

## Notes

- Never copy the private key onto a media-ingest host. The whole point of the
  public-key scheme is that those hosts cannot read what they park.
- Rotating the key means generating a new pair, importing the new public half
  on both hosts (`/opt/media-ingest*/park_pub.asc`), and storing the private half
  in the password manager; old ciphertext then needs the old private key.
