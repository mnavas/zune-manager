# Installation Guide

zune-manager is a **Linux** command-line tool. It drives the compiled
**XuneSyncLibrary** MTP tools for the actual transfer, and uses **ffmpeg** and
**mutagen** for transcoding and tagging. There is no build step for zune-manager
itself — it's plain Python 3 scripts.

> **Platform:** Linux only. The USB-reset and gvfs-handling, the MTPZ connection,
> and the XuneSyncLibrary build are all Linux-specific. macOS/Windows are not
> supported.

---

## Prerequisites

| Requirement | Why | How |
|-------------|-----|-----|
| **Python 3.10+** | runs the scripts | your distro's `python3` |
| **ffmpeg / ffprobe** | tag probing, FLAC→MP3, cover rescale | `apt install ffmpeg` |
| **Python `mutagen`** | writes the ID3v2.3 tags | see [below](#installing-mutagen) |
| **XuneSyncLibrary (built)** | the MTP upload + artist tools | [build it](#1--build-xunesynclibrary) |
| **`~/.mtpz-data`** | MTPZ auth keys for the Zune HD | [MTPZ keys](#3--mtpz-keys) |

No account, API key, or paid service is required. MusicBrainz and the Cover Art
Archive are free public services; everything else runs locally.

---

## 1 — Build XuneSyncLibrary

zune-manager calls four compiled tools from
[XuneSyncLibrary](https://github.com/xune-software/XuneSyncLibrary):

- `upload_test_cli` — uploads a staged folder to the device
- `delete_artist` — removes an artist (used by `--replace`)
- `merge_artist` — safely consolidates duplicate artist objects
- `set_artist_media_id` — also used to list the artist objects on the device

Build the library per its own README, then tell zune-manager where the build
directory is:

```bash
export XUNE_BUILD=~/Code/XuneSyncLibrary/build
```

If `XUNE_BUILD` is unset, zune-manager defaults to `~/Code/XuneSyncLibrary/build`.
Add the `export` line to your `~/.bashrc` to make it permanent.

---

## 2 — Install zune-manager

```bash
git clone https://github.com/mnavas/zune-manager.git
cd zune-manager
```

That's the whole install — the scripts run in place.

### Installing mutagen

On modern Debian/Ubuntu the system Python is **externally managed** (PEP 668),
so `pip install mutagen` is blocked. Use one of:

```bash
# A — system package (needs sudo)
sudo apt install python3-mutagen

# B — a project-local venv that still sees system packages (ffmpeg stays available)
python3 -m venv --system-site-packages .venv
.venv/bin/pip install mutagen
```

With a venv, run the tool with the venv's interpreter:

```bash
.venv/bin/python zune_add.py "/path/to/album"
```

(Elsewhere in these docs the command is written as `python3 zune_add.py …`;
substitute `.venv/bin/python` if you went the venv route.)

---

## 3 — MTPZ keys

The Zune HD speaks **MTPZ** (Microsoft's authenticated MTP variant). The
XuneSyncLibrary stack needs the MTPZ key file present at:

```
~/.mtpz-data
```

Without it the device will be seen on USB but refuse the data connection. See the
XuneSyncLibrary documentation for obtaining the key file.

---

## 4 — Connecting the Zune HD

On Linux the Zune HD can be fussy: GNOME's `gvfsd-mtp` grabs the device, and the
MTP stack sometimes wedges on reconnect. zune-manager handles this automatically
before every upload — it resets the USB port and stops `gvfsd-mtp` — so normally
you just plug the device in.

If a connection still fails:

```bash
# Confirm the kernel sees it (Microsoft 045e:063e = Zune HD)
lsusb | grep -i 045e:063e

# Stop the auto-mounter by hand if needed
pkill -x gvfsd-mtp
```

Then re-run the command. Unlock the device screen if it's asleep.

---

## Verifying the setup

A dry run exercises everything except the upload — tag probing, the MusicBrainz
lookup, cover fetch, and staging — without touching the device:

```bash
python3 zune_add.py "/path/to/album" --dry-run
```

It prints the matched release and the proposed track list, then stages the files
to a temp folder and stops. If that works, you're ready to add albums for real —
see the [User Guide](user-guide.md).

---

## Dependencies at a glance

| Component | Role |
|-----------|------|
| `python3` (3.10+) | runs `zune_add.py` / `zunelib.py` / `zune_batch.py` |
| `ffmpeg` / `ffprobe` | read tags, transcode to MP3 320, rescale cover art |
| `mutagen` | write ID3v2.3 tags + embed the cover |
| XuneSyncLibrary tools | MTP upload, delete, and the safe artist merge |
| `~/.mtpz-data` | MTPZ authentication for the Zune HD |
