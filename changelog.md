# Changelog

## v0.1.0

First public release.

- **One-command album loader** (`zune_add.py`): detect → MusicBrainz lookup →
  Cover Art Archive → FLAC/OGG/etc → MP3 320 → ID3v2.3 tags + embedded 500 px
  cover → USB upload → automatic artist de-duplication.
- **Safe artist merge** after every upload — re-points a newly-created duplicate
  artist's album + tracks to the original object and removes the empty duplicate,
  so an artist never appears twice. Never deletes an object that still owns tracks.
- **Batch mode** (`zune_batch.py`) — add several album folders in one run with an
  OK / FAIL summary.
- **Options**: `--dry-run`, `--yes`, `--artist`, `--album`, `--genre`,
  `--no-online`, `--replace`.
- **Track-title guard** — MusicBrainz titles are used only when the matched
  edition's track count equals the local file count; otherwise file titles are
  kept (a deluxe/live edition can't clobber the standard tracklist).
- **Linux USB handling** — `USBDEVFS_RESET` + stop `gvfsd-mtp` before uploading,
  and reset again before the post-upload merge to avoid the reconnect wedge.
- **No personal data in the source** — `XUNE_BUILD` defaults via `~` expansion
  and the MusicBrainz User-Agent is overridable with `ZUNE_USER_AGENT`.
- Added a landing page (`index.html`) and full docs (`docs/installation.md`,
  `docs/user-guide.md`, `docs/architecture.md`).
