# zune-manager — Architecture & Developer Guide

## Overview

zune-manager is a small Python CLI with a deliberately thin structure: one
orchestrator (`zune_add.py`), one helper library (`zunelib.py`), and a batch
wrapper (`zune_batch.py`). All device access is delegated to the compiled
**XuneSyncLibrary** tools — zune-manager never speaks MTP itself; it prepares
files and metadata, then shells out to those tools.

The design splits cleanly into three concerns:

- **Online metadata** — MusicBrainz lookup + Cover Art Archive (pure HTTP, no device).
- **Local media** — ffprobe tag reading, FLAC→MP3 transcode, cover rescale, ID3 tagging.
- **Device control** — USB reset, gvfs handling, and the XuneSyncLibrary subprocess calls.

Only the device-control layer needs the Zune plugged in, so metadata and staging
are fully exercised by `--dry-run`.

---

## Module Map

```
zune-manager/
├── zune_add.py     Orchestrator — CLI, detect → lookup → art → plan → stage → upload → merge
├── zunelib.py      Helpers — device control, MusicBrainz/CAA, convert, tag, dataclasses
├── zune_batch.py   Runs several album folders in sequence, forwards args after `--`
├── README.md       Overview + usage
├── changelog.md    Version history
├── docs/           installation · user-guide · architecture
└── assets/         deuna-qr.png (support)
```

`zune_add.py` imports `zunelib as z`; `zune_batch.py` just subprocesses
`zune_add.py` once per folder. Nothing else is interdependent.

---

## Configuration (`zunelib.py` top)

| Constant | Meaning | Override |
|----------|---------|----------|
| `XUNE_BUILD` | XuneSyncLibrary build dir (holds the tools) | env `XUNE_BUILD` |
| `UPLOAD_TOOL` / `DELETE_TOOL` / `MERGE_TOOL` / `SETID_TOOL` | the four tool paths | via `XUNE_BUILD` |
| `ZUNE_VID` / `ZUNE_PID` | `045e` / `063e` — the Zune HD USB id | — |
| `USER_AGENT` | MusicBrainz User-Agent (asks for a contact) | env `ZUNE_USER_AGENT` |
| `ZUNE_OK_EXT` | formats the Zune plays (no transcode) | — |
| `AUDIO_EXT` | all recognised audio extensions | — |
| `ART_SIZE` | embedded cover size, `500` px | — |
| `MP3_BITRATE` | transcode target, `320k` | — |

No personal data is baked in: the build path uses `~` via `expanduser`, and the
User-Agent is a neutral default you can override with `ZUNE_USER_AGENT` to add
your own contact.

---

## The Pipeline (`zune_add.py:main`)

```
find_audio(folder)                     # recurse, collect known audio extensions
detect_album(files)                    # most-common album_artist / album / genre from tags
musicbrainz_lookup(artist, album, n)   # canonical release (unless --no-online)
fetch_cover(mb, [cover.jpg, folder.jpg])  # CAA front, else local fallback
   → make_baseline_cover(...)          # rescale to 500px baseline JPEG
build plan [{src, pos, title, convert}]   # per-track, titles guarded (see below)
print plan → confirm (unless --yes / --dry-run)
for each track:
    to_mp3(src, dst) or copy           # transcode only what the Zune can't play
    write_id3(dst, …, cover, mbid)     # ID3v2.3 tags + APIC
prepare_device()                       # USB reset + kill gvfsd-mtp
[--replace] device_delete_artist(...)  # optional clean slate
device_upload(stage)                   # XuneSyncLibrary upload_test_cli
device_merge_artist(artist)            # safe de-dup
```

### The track-title guard

```python
use_mb_titles = bool(mb and len(mb.tracks) == len(files))
```

MusicBrainz titles overwrite file titles **only** when the matched edition's
track count equals the local file count. This stops a deluxe/live/JP edition from
renaming the standard album's tracks. Album, artist, and year are always taken
from MusicBrainz regardless; `total` in `track/total` is the local file count
(these are full-album uploads).

---

## Online Metadata (`zunelib.py`)

### `musicbrainz_lookup(artist, album, expected_tracks)` → `MBResult | None`

Two-stage lookup against the MusicBrainz WS/2 API (1 s sleeps between calls for
the rate limit):

1. **Release-group search** — `release-group?query=artist:"…" AND release:"…"`.
   Candidates are ranked by `rg_score`:
   - exact title match first (`== album`, then substring, then other);
   - **reject** live/compilation/remix/DJ-mix/mixtape secondary types (bogus tracklists);
   - prefer `primary-type == "Album"`;
   - then the MB relevance score.
2. **Release pick** — among the chosen group's releases, `score` prefers an exact
   `track-count == expected_tracks`, then `Official` status, then fewest tracks
   (standard over deluxe). The earliest release date across the group becomes the
   year. The tracklist is read from that release (`inc=recordings`).

`MBResult` carries `artist`, `artist_mbid`, `album`, `date`, `release_mbid`,
`release_group_mbid`, and `tracks` (`[{position, title}]`).

### `fetch_cover(mb, fallback_paths)` → `bytes | None`

Tries the Cover Art Archive front image for the **release**, then the
**release-group**, verifying the JPEG magic (`FF D8`). If neither is available (or
`mb` is `None`), it falls back to the first existing path in `fallback_paths`
(`cover.jpg` / `folder.jpg` / `Folder.jpg` in the album folder).

HTTP goes through `_http_json` / `_http_bytes`, both of which set `USER_AGENT` and
fail soft (log + `None`) so a MusicBrainz 503 degrades gracefully to file tags.

---

## Local Media (`zunelib.py`)

| Function | Role |
|----------|------|
| `ffprobe_tags(path)` | Read format tags as a lower-cased dict (via `ffprobe -show_entries format_tags`) |
| `needs_conversion(path)` | `True` unless the extension is in `ZUNE_OK_EXT` |
| `to_mp3(src, dst)` | ffmpeg → MP3 `320k`, `-map 0:a`, `-map_metadata 0`, `-id3v2_version 3` |
| `make_baseline_cover(data, dst, size=500)` | ffmpeg rescale to `size×size`, `yuvj420p` (baseline JPEG) |
| `write_id3(path, …)` | mutagen ID3v2.3 writer (below) |
| `find_audio(folder)` | Recursive, sorted, extension-filtered collection |
| `most_common(vals)` | Pick the modal non-empty value (for detection) |

### `write_id3(...)`

Builds a clean ID3 tag set and saves **v2.3** (`t.save(path, v2_version=3)` — the
version the Zune HD reads reliably). Each frame is `delall`-ed then re-added:
`TIT2` title, `TPE1`/`TPE2` artist + album-artist, `TALB` album, `TRCK`
`track/total`, optional `TCON` genre, `TYER`+`TDRC` year, `APIC` cover
(`type=3`, "Cover", image/jpeg), and `TXXX:MusicBrainz Artist Id`.

---

## Device Control (`zunelib.py`)

All device access is a subprocess call to a XuneSyncLibrary tool, wrapped by
`_run_tool(argv, timeout)` which sets `LD_LIBRARY_PATH=XUNE_BUILD` and captures
output (returning `(124, …)` on timeout).

| Function | Tool / action |
|----------|---------------|
| `zune_usb_node()` | Parse `lsusb` for `045e:063e` → `/dev/bus/usb/BBB/DDD` |
| `usb_reset()` | `USBDEVFS_RESET` ioctl on that node (clears the reconnect wedge) |
| `kill_gvfs_mtp()` | `pkill -x gvfsd-mtp` (release GNOME's auto-mount grab) |
| `prepare_device()` | reset → wait for re-enumeration → kill gvfs → confirm present |
| `device_upload(folder)` | `upload_test_cli <folder> --verbose` |
| `device_delete_artist(name)` | `delete_artist <name>` (for `--replace`) |
| `device_list_artist_objects()` | parse `set_artist_media_id` output → `[(obj_id, name)]` |
| `device_merge_artist(name)` | **reset first**, then `merge_artist <name>` |

### Why `prepare_device()` exists

On Linux two things fight the Zune HD: GNOME's `gvfsd-mtp` claims the device the
moment it's plugged in, and the MTP stack can wedge on the reconnect that follows
an upload. `prepare_device()` runs a `USBDEVFS_RESET`, waits for the device to
re-enumerate, then kills `gvfsd-mtp` — making the connection reliable.

### Why `device_merge_artist` resets first

The merge runs *after* an upload, i.e. right after the device has reconnected —
exactly the wedge-prone moment. If the merge tool runs against a wedged device it
silently no-ops. So `device_merge_artist` calls `prepare_device()` **before**
invoking `merge_artist`.

---

## Device-Safety Rules (read before changing device code)

These are hard-won and easy to get catastrophically wrong:

- **Never delete an artist object that still owns tracks.** On the Zune HD,
  deleting an artist object (property `0xB218`) **cascade-deletes its albums and
  tracks**. Deleting a "duplicate" artist the naïve way once wiped an entire
  artist's music.
- **De-dup by merging, not deleting.** `merge_artist` re-points each duplicate's
  albums + tracks (artist-grouping property `0xDAB9`) to the keeper (lowest object
  id = the original), re-indexes, and only then deletes the now-**empty**
  duplicate objects (safe — nothing references them).
- **Reset before the post-upload merge** (see above).
- **`--replace` is the blunt instrument** — it deletes the whole artist on
  purpose. For a single album use the `delete_album` tool instead.

---

## Running in Development

```bash
cd zune-manager
export XUNE_BUILD=~/Code/XuneSyncLibrary/build
# metadata + staging only, no device needed:
python3 zune_add.py "/path/to/album" --dry-run
```

`--dry-run` exercises detection, the MusicBrainz lookup, cover fetch, transcode,
and tagging, and leaves the staged files in a temp folder it prints — the whole
pipeline minus the device. Add a `cover.jpg` to the album folder to test the
offline cover path. See the [changelog](../changelog.md) for version history.
