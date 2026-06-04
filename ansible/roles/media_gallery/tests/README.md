# Gallery SPA tests (jsdom)

Headless tests for gallery_index.html — the SPA can't be clicked through manually
(it's behind Authentik SSO), so these load the real file in jsdom with a stubbed
fetch + fake manifest and exercise selection / bulk move / bulk delete / the
selection-survives-background-refresh race.

Run:  cd <tmpdir> && npm install jsdom && node test_*.js
(point the require() path at ansible/roles/media_gallery/files/gallery_index.html)

Regressions these guard against:
- Set selection read via Array.prototype.slice.call(Set) returns [] -> "nothing
  selected" on every bulk action. MUST use Array.from(selected).
- openFolder() unconditionally clearing the selection -> background reloadManifest
  re-render wipes an in-progress selection. Only clear on real navigation.
