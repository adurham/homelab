# Gallery — file-manager feature status & roadmap

The gallery SPA (`files/gallery_index.html`) served at `/` via lb-01, backed by
`upload_service.py` (mutations), `thumb_service.py` (posters), `trash_service.py`
(delete), and `build_manifest.py` (the item index). Tests live in `tests/`
(jsdom; the live app is behind Authentik SSO so it can't be clicked through
manually — run the tests instead).

## Shipped (Finder/Explorer parity)

Navigation:    folder grid landing, breadcrumb (Gallery › folder), back button,
               lightbox viewer (image+video, prev/next, keyboard)
Selection:     always-on per-tile checkbox, select-all/clear, rubber-band
               drag-select, ctrl/cmd-click toggle, shift-click range select
View:          grid ⇄ list/details toggle, thumbnail zoom slider, sort by
               date / name / size / type, status bar (count + selection)
Search:        live filter box (name/folder), '/' to focus, Esc clears
Mutations:     upload (button+drag), new folder, rename folder, delete folder,
               rename file, move (bulk / drag-to-rail / drag-to-folder-tile /
               lightbox / context-menu), delete (bulk / per-item / context /
               keyboard Delete), single-file download
Interaction:   right-click context menu (Open/Move/Rename/Download/Properties/
               Delete), Properties dialog (name/folder/type/size/date/path),
               keyboard control (arrows/Space/Enter/Delete/Ctrl-A/Esc)
Feedback:      OS-style progress dialog, toasts, optimistic updates with
               client-authoritative pending state (moves/deletes reflect
               instantly and survive the ~20s server manifest debounce)

Backend endpoints (upload_service): /mkdir /upload /rename /renamefile /move
/rmdir /status ; /trash (trash_service) ; /thumb (thumb_service).
Manifest items carry: stem, chat, file, thumb, type, date, size.

## Not yet built (optional — deliberate deferrals, with the why)

1. ZIP DOWNLOAD OF A SELECTION
   Single-file download works (browser GETs the original). A multi-select "export
   as .zip" needs a backend streaming endpoint: auth the request, rclone-cat each
   selected original into a streamed ZIP (zipstream) so we never buffer GBs on the
   8GB→32GB CT disk. ~60-line endpoint + nginx route + UI button. Medium effort.
   Deferred because single download covers the common case.

2. REAL TRASH WITH RESTORE (soft delete)
   Today /trash HARD-deletes the original+thumb and appends the stem to an
   exclusion ledger (so it never re-downloads). There is no restore. A Finder-style
   Trash would instead MOVE the original to a `gcrypt:trash/<stem>` area + a
   trash-manifest, expose a Trash folder in the UI, and add /restore + /empty-trash.
   This is the biggest remaining item (storage-model change + UI surface). Deferred
   because delete is currently intentional/permanent and the move feature already
   covers "I put it in the wrong place."

3. THUMBNAIL-SIZE / VIEW PERSISTENCE
   Zoom + grid/list reset on reload. Could persist to localStorage. Trivial; skipped
   to avoid scope creep.

## Notable engineering gotchas (don't regress these)
- Selection is a JS Set: read it with `Array.from(selected)`, NOT
  `Array.prototype.slice.call()` (returns [] for a Set — silently breaks bulk ops).
- `openFolder()` must only `clearSelection()` on REAL navigation, not on a
  same-folder background `reloadManifest` re-render (else it wipes an in-progress
  selection).
- After a move/delete, the server manifest is debounced ~20s, so an immediate
  refetch returns STALE data. The client keeps `pendingMove`/`pendingDel` and
  applies them to every manifest load until the server agrees (then retires them).
- The grid/lightbox index into a filtered+sorted `shown[]` array, not the raw
  folder `view[]` — keep tile click / lightbox / drag using `shown[i]`.
- rclone serve renders its own dir listing at `/`; nginx must serve the SPA via
  `location = /` → `/gallery/index.html`, with everything else falling through.
