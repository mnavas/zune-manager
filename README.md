# zune-manager

Automated album loader for the **Zune HD** on Linux. Point it at an album
folder and it does the whole pipeline in one command:

1. Detects the artist/album from tags (or folder name)
2. Looks up canonical metadata on **MusicBrainz** (correct titles, track order, year)
3. Fetches cover art from the **Cover Art Archive** (falls back to a local `cover.jpg`)
4. **Transcodes FLAC/OGG/etc → MP3 320** (the Zune HD can't play FLAC)
5. Writes clean **ID3v2.3** tags + embedded baseline-JPEG cover + MusicBrainz Artist Id
6. Resets USB / stops the `gvfsd-mtp` auto-mounter, then uploads
7. **Consolidates the artist** — adding an album to an artist already on the
   device won't leave a second "Artist" heading. This is a *safe merge*
   (re-points the new album/tracks to the original artist, then removes the
   empty duplicate). It never deletes an artist object that still owns tracks —
   on the Zune HD that cascade-deletes the music.

## Requirements
- The compiled XuneSyncLibrary tools in `XUNE_BUILD`
  (`upload_test_cli`, `delete_artist`, `delete_object`, `set_artist_media_id`).
  Override the path with `export XUNE_BUILD=/path/to/XuneSyncLibrary/build`.
- `~/.mtpz-data` present (MTPZ auth keys for the Zune HD).
- `ffmpeg`/`ffprobe`, and Python `mutagen`.

On Debian/Ubuntu the system Python is externally-managed (PEP 668), so
`pip install mutagen` is blocked. Install it one of these ways:

```bash
# system package (needs sudo)
sudo apt install python3-mutagen

# or a project-local venv that also sees system packages (ffmpeg, etc.)
python3 -m venv --system-site-packages .venv
.venv/bin/pip install mutagen
# then run the tool with the venv's interpreter:
.venv/bin/python zune_add.py "/path/to/album"
```

## Usage
```bash
# Add one album (asks for confirmation after showing the plan)
python3 zune_add.py "/path/to/Artist - Album (2024) [FLAC]"

# No prompt, and preview only:
python3 zune_add.py "/path/to/album" --yes
python3 zune_add.py "/path/to/album" --dry-run

# Replace an album already on the device (clean re-add of the whole artist):
python3 zune_add.py "/path/to/album" --replace

# Overrides when detection/lookup is wrong:
python3 zune_add.py "/path/to/album" --artist "Artist Name" --album "Album Title"
python3 zune_add.py "/path/to/album" --no-online     # trust the existing tags

# Add several albums in a row:
python3 zune_batch.py "/path/AlbumA" "/path/AlbumB" "/path/AlbumC"
```

## Notes / limitations
- Zune HD plays MP3 / WMA / AAC(m4a); FLAC/OGG are transcoded to MP3 320.
- `--replace` deletes the **entire** artist from the device first, so only use
  it when the folder contains everything you want for that artist.
- Artist **background images** are a separate, unsolved problem (the device
  won't fetch them without Zune-account auth); this tool handles music,
  metadata, and album art.

## Files
- `zune_add.py` — the CLI orchestrator
- `zunelib.py`  — device control, MusicBrainz/CAA lookup, conversion, tagging
- `zune_batch.py` — add multiple album folders in one run
