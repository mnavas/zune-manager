# zune-manager — User Guide

## What is zune-manager?

zune-manager adds an **album folder** to a **Zune HD** in one command. It figures
out what the album is, fixes the metadata against MusicBrainz, fetches the real
cover art, converts anything the Zune can't play, writes clean tags, uploads over
USB, and then tidies up so you don't end up with the artist listed twice.

The whole point is that you never hand-edit tags, hunt for cover art, convert
FLAC by hand, or fight the Zune's Linux MTP connection — it's one command per
album.

> **Before you start:** make sure the setup from the
> [Installation Guide](installation.md) is done — XuneSyncLibrary built,
> `XUNE_BUILD` pointed at it, `mutagen` installed, and `~/.mtpz-data` in place.

---

## The command at a glance

```bash
python3 zune_add.py "<album folder>" [options]
```

| Step | What happens |
|------|--------------|
| 1. Detect | Reads the folder's tags to guess artist + album |
| 2. Look up | Queries MusicBrainz for the canonical release |
| 3. Art | Fetches the front cover (Cover Art Archive, or local `cover.jpg`) |
| 4. Plan | Prints the proposed upload and waits for your OK |
| 5. Stage | Transcodes + tags into a temp folder |
| 6. Upload | Resets USB, uploads over MTP |
| 7. Merge | Consolidates any duplicate artist heading |

---

## Adding your first album

```bash
python3 zune_add.py "/music/The Warning - Everything's Falling (2026)"
```

You'll see something like:

```
Found 12 audio file(s) in The Warning - Everything's Falling (2026)
Detected: artist='The Warning'  album='Everything's Falling'  genre='-'
Looking up MusicBrainz…
  match: The Warning — Everything's Falling (2026)  [12 tracks]  mbid=7f625f35…
Cover art: ok (313 KB source)

=== Proposed upload ===
  The Warning — Everything's Falling (2026)
    1. Ritual
    2. Perfect Daughter
    3. Everything's Falling
    …

Proceed? [y/N]
```

Type `y` to go ahead. It stages the tracks, preps the device, uploads, and
finishes with a short merge summary and `✓ Done.`

---

## What gets fixed

- **Artist / album / year** — always taken from the matched MusicBrainz release,
  so casing and punctuation are canonical.
- **Track titles** — taken from MusicBrainz **only when the matched edition has
  the same number of tracks as your folder**. Otherwise your file titles are kept
  (so a 32-track deluxe or a live edition can't overwrite the standard tracklist).
  You'll see `(keeping file titles — MB edition has N tracks, you have M)` when
  that guard kicks in.
- **File names on the device** — each track is named `NN - Title.mp3` in track
  order, with `/` replaced by `_`.
- **Tags** — rewritten as **ID3v2.3**: title, artist, album-artist,
  `track/total`, year, genre, embedded cover, and the MusicBrainz Artist Id.
- **Cover art** — rescaled to a **500 px baseline JPEG** (the format the Zune HD
  renders cleanly) and embedded on every track.
- **Format** — FLAC/OGG/OPUS/WAV/ALAC are transcoded to **MP3 320 kbps**; files
  the Zune already plays (MP3/WMA/AAC/M4A) are copied through untouched.

---

## Options

| Option | What it does |
|--------|--------------|
| `--dry-run` | Show the plan and stage the files, but **don't** upload. Prints the temp folder so you can inspect it. |
| `--yes` | Skip the `Proceed?` prompt (for scripting / batches). |
| `--artist "NAME"` | Override the detected album-artist (when detection or the MB match is wrong). |
| `--album "NAME"` | Override the detected album title. |
| `--genre "G"` | Set the genre tag. |
| `--no-online` | Skip MusicBrainz entirely and trust the existing file tags. |
| `--replace` | Delete this artist from the device **first**, then add — a clean re-add. |

### Previewing with `--dry-run`

Always safe — it never touches the device:

```bash
python3 zune_add.py "/music/some album" --dry-run
```

Use it to confirm the MusicBrainz match and track order before committing, or to
check a tricky album where detection might be off.

### Overrides

When the tags are sparse or MusicBrainz picks the wrong release:

```bash
python3 zune_add.py "/music/weird-folder" --artist "BABYMETAL" --album "METAL FORTH"
python3 zune_add.py "/music/bootleg" --no-online      # trust my own tags
```

### Replacing an album

`--replace` deletes the **entire artist** from the device first, then re-adds
from your folder. Use it only when your folder has everything you want for that
artist — otherwise you'll lose the other albums. To swap just one album, see
[Swapping a single album](#swapping-a-single-album) below.

```bash
python3 zune_add.py "/music/Artist - Full Discography Folder" --replace
```

---

## Why there's never a duplicate artist

On the Zune HD, each track and album carries a property pointing at its owning
**artist object**. When you upload an album for an artist that's *already* on the
device, the uploader creates a **second** artist object — so the browse view
shows the artist twice.

After every successful upload, zune-manager runs a **safe merge**:

1. Re-points the new album + tracks to the **original** artist object.
2. Re-indexes the device.
3. Deletes the now-empty duplicate artist object.

It **never deletes an artist object that still owns tracks** — on the Zune HD
that cascade-deletes the music. That's why it merges rather than "deleting the
duplicate." You'll see a short summary like:

```
Consolidating artist (merge any duplicate)…
  Artist 'The Warning': keeper=0x8003027  duplicates=0x8003100
  album 0x6003104 (…) + 12 tracks -> keeper
  deleting empty duplicate artist 0x8003100
```

---

## Adding several albums at once

`zune_batch.py` runs a list of folders in sequence (always non-interactively):

```bash
python3 zune_batch.py "/music/Album A" "/music/Album B" "/music/Album C"
```

Pass extra `zune_add.py` flags after a `--`:

```bash
python3 zune_batch.py "/music/A" "/music/B" -- --replace
```

It prints a per-album `OK` / `FAIL` summary at the end and exits non-zero if any
album failed.

---

## Swapping a single album

To replace just one album (e.g. a partial rip for the full one) without touching
the rest of the artist, use the XuneSyncLibrary `delete_album` tool to remove
that one album, then add the full folder — the auto-merge keeps the artist
single:

```bash
# remove just that album
$XUNE_BUILD/delete_album "The Warning" "Error"
# add the full version
python3 zune_add.py "/music/The Warning - Error (full)"
```

---

## Cover art

- **Online:** fetched from the Cover Art Archive for the matched release (then the
  release-group), rescaled to 500 px baseline JPEG, embedded on every track.
- **Offline / no match:** drop a `cover.jpg` (or `folder.jpg`) in the album folder
  and it's used as the fallback.
- If your source files already have embedded art but no match is found, you can
  extract it into the folder as `cover.jpg` so it's picked up:

  ```bash
  ffmpeg -i "01 - track.mp3" -an -c:v copy cover.jpg
  ```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Zune HD not ready` | Plug it in, unlock the screen, re-run. Check `lsusb \| grep 045e:063e`. |
| `No such file … upload_test_cli` | `XUNE_BUILD` is wrong — point it at your XuneSyncLibrary build. |
| `ModuleNotFoundError: mutagen` | Install it (see [Installation](installation.md#installing-mutagen)); run via `.venv/bin/python` if you used a venv. |
| `Cover art: none found` | No match + no local `cover.jpg`. Add one to the folder. |
| MusicBrainz `503` | Transient rate-limit. Re-run; titles fall back to your files until it recovers. |
| Wrong release matched | Use `--artist` / `--album`, or `--no-online` to trust your tags. |
| Device wedges mid-upload | Unplug/replug, `pkill -x gvfsd-mtp`, re-run. The tool resets USB each run. |

See [architecture.md](architecture.md) for how each stage works under the hood,
and the [changelog](../changelog.md) for version history.
