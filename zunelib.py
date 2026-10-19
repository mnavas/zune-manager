"""
zunelib — core helpers for the Zune HD manager.

Wraps the compiled XuneSyncLibrary tools (upload_test_cli, delete_artist,
set_artist_media_id) plus online metadata lookup (MusicBrainz + Cover Art
Archive), FLAC/other -> MP3 conversion, and ID3 tagging for Zune HD.
"""
from __future__ import annotations
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# ── Configuration ──────────────────────────────────────────────────────────
XUNE_BUILD = os.environ.get("XUNE_BUILD", os.path.expanduser("~/Code/XuneSyncLibrary/build"))
UPLOAD_TOOL = os.path.join(XUNE_BUILD, "upload_test_cli")
DELETE_TOOL = os.path.join(XUNE_BUILD, "delete_artist")
SETID_TOOL = os.path.join(XUNE_BUILD, "set_artist_media_id")
MERGE_TOOL = os.path.join(XUNE_BUILD, "merge_artist")
ZUNE_VID = "045e"
ZUNE_PID = "063e"                       # Zune HD (Pavo)
# MusicBrainz asks for an identifying User-Agent with a contact.
# Set ZUNE_USER_AGENT to add your own contact (email or URL).
USER_AGENT = os.environ.get(
    "ZUNE_USER_AGENT", "ZuneManager/0.1 (+https://github.com/zune-manager)")

# Zune HD plays these natively; everything else must be transcoded to MP3.
ZUNE_OK_EXT = {".mp3", ".wma", ".m4a", ".aac", ".mp4"}
AUDIO_EXT = ZUNE_OK_EXT | {".flac", ".ogg", ".opus", ".wav", ".alac"}
ART_SIZE = 500                          # embedded cover px (baseline jpeg)
MP3_BITRATE = "320k"


def log(msg: str):
    print(msg, flush=True)


# ── Device control ─────────────────────────────────────────────────────────
def zune_usb_node() -> str | None:
    """Return /dev/bus/usb/BBB/DDD for the connected Zune HD, or None."""
    try:
        out = subprocess.check_output(["lsusb"], text=True)
    except Exception:
        return None
    for line in out.splitlines():
        if f"{ZUNE_VID}:{ZUNE_PID}" in line.lower():
            m = re.match(r"Bus (\d+) Device (\d+):", line)
            if m:
                return f"/dev/bus/usb/{m.group(1)}/{m.group(2)}"
    return None


def usb_reset() -> bool:
    """USBDEVFS_RESET the Zune to clear the reconnect-wedge state."""
    node = zune_usb_node()
    if not node:
        return False
    USBDEVFS_RESET = ord("U") << 8 | 20
    try:
        fd = os.open(node, os.O_WRONLY)
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        os.close(fd)
        return True
    except Exception as e:
        log(f"  usb_reset failed: {e}")
        return False


def kill_gvfs_mtp():
    subprocess.run(["pkill", "-x", "gvfsd-mtp"], stderr=subprocess.DEVNULL)


def prepare_device(timeout=20) -> bool:
    """Reset + wait for re-enumeration + stop the gvfs auto-mounter."""
    if not zune_usb_node():
        log("  No Zune HD detected on USB.")
        return False
    usb_reset()
    for _ in range(timeout):
        if zune_usb_node():
            break
        time.sleep(1)
    time.sleep(1)
    kill_gvfs_mtp()
    time.sleep(1)
    return zune_usb_node() is not None


def _run_tool(argv, timeout) -> tuple[int, str]:
    env = dict(os.environ, LD_LIBRARY_PATH=XUNE_BUILD)
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, (e.output or "") + "\n[timeout]"


def device_upload(folder: str, timeout=600, dry_run=False) -> tuple[int, str]:
    argv = [UPLOAD_TOOL, folder, "--verbose"] + (["--dry-run"] if dry_run else [])
    return _run_tool(argv, timeout)


def device_delete_artist(name: str, timeout=180, dry_run=False) -> tuple[int, str]:
    argv = [DELETE_TOOL, name] + (["--dry-run"] if dry_run else [])
    return _run_tool(argv, timeout)


def device_list_artist_objects(timeout=120) -> list[tuple[int, str]]:
    """List (object_id, name) for every artist metadata object on the device.
    set_artist_media_id prints the full artist listing before matching."""
    rc, out = _run_tool([SETID_TOOL, "__none__", "00000000-0000-0000-0000-000000000000"], timeout)
    objs = []
    for line in out.splitlines():
        m = re.match(r"\s*0x([0-9a-fA-F]+)\s+(.*\S)\s*$", line)
        if m:
            objs.append((int(m.group(1), 16), m.group(2)))
    return objs


def device_list_artists(timeout=120) -> list[str]:
    return [n for _, n in device_list_artist_objects(timeout)]


def device_merge_artist(name: str) -> tuple[int, str]:
    """Safely collapse duplicate artist objects of `name` into one.

    NEVER deletes music: the merge_artist tool re-points the duplicates'
    albums+tracks (prop 0xDAB9) to the original artist object, re-indexes, then
    deletes only the now-empty duplicate artist objects. (Deleting an artist
    object that still owns tracks would cascade-delete them — hence merge, not
    delete.)"""
    prepare_device()   # reset first — avoids the post-upload reconnect wedge
    return _run_tool([MERGE_TOOL, name], 240)


# ── Online metadata (MusicBrainz + Cover Art Archive) ──────────────────────
def _http_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception as e:
        log(f"  http error: {e}")
        return None


def _http_bytes(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:
        return None


@dataclass
class MBResult:
    artist: str = ""
    artist_mbid: str = ""
    album: str = ""
    date: str = ""
    release_mbid: str = ""
    release_group_mbid: str = ""
    tracks: list[dict] = field(default_factory=list)   # {position, title}


def musicbrainz_lookup(artist: str, album: str, expected_tracks: int = 0) -> MBResult | None:
    """Find the best matching release and return canonical metadata.

    Prefers the edition whose track count matches the local files (so the
    standard album wins over deluxe/box editions), and uses the earliest
    release date for the year.
    """
    q = f'artist:"{artist}" AND release:"{album}"'
    url = "https://musicbrainz.org/ws/2/release-group?query=" + urllib.parse.quote(q) + "&fmt=json&limit=5"
    d = _http_json(url)
    if not d or not d.get("release-groups"):
        return None
    # Choose the best release-group: exact title match, a studio Album, and
    # NOT a live/compilation/remix edition (those have bogus tracklists).
    al = album.strip().lower()
    LIVEISH = {"Live", "Compilation", "Remix", "DJ-mix", "Mixtape/Street"}
    def rg_score(rg):
        title = (rg.get("title") or "").strip().lower()
        exact = 0 if title == al else (1 if al in title or title in al else 2)
        sec = set(rg.get("secondary-types") or [])
        liveish = 1 if sec & LIVEISH else 0
        not_album = 0 if rg.get("primary-type") == "Album" else 1
        return (exact, liveish, not_album, -int(rg.get("score") or 0))
    rg = sorted(d["release-groups"], key=rg_score)[0]
    res = MBResult(
        album=rg.get("title", album),
        release_group_mbid=rg.get("id", ""),
        date=(rg.get("first-release-date") or "")[:4],
    )
    ac = rg.get("artist-credit") or []
    if ac:
        res.artist = ac[0].get("name", artist)
        res.artist_mbid = ac[0].get("artist", {}).get("id", "")
    time.sleep(1.0)  # MB rate limit
    url = f"https://musicbrainz.org/ws/2/release?release-group={res.release_group_mbid}&fmt=json&limit=50"
    d = _http_json(url)
    rels = (d or {}).get("releases", [])
    if not rels:
        return res
    # earliest date across all releases → album year
    dates = sorted(r["date"][:4] for r in rels if r.get("date"))
    if dates:
        res.date = dates[0]
    # choose the release to take the tracklist from: exact track-count match,
    # else Official with the fewest tracks (standard over deluxe).
    def score(r):
        tc = r.get("track-count") or 0
        exact = 0 if (expected_tracks and tc == expected_tracks) else 1
        return (exact, r.get("status") != "Official", tc)
    rels.sort(key=score)
    res.release_mbid = rels[0]["id"]
    time.sleep(1.0)
    d = _http_json(f"https://musicbrainz.org/ws/2/release/{res.release_mbid}?inc=recordings&fmt=json")
    for m in (d or {}).get("media", []):
        for t in m.get("tracks", []):
            res.tracks.append({"position": t.get("position"), "title": t.get("title")})
    return res


def fetch_cover(mb: MBResult | None, fallback_paths: list[str]) -> bytes | None:
    """Cover art: Cover Art Archive first, then a local cover file."""
    if mb:
        for kind, mbid in (("release", mb.release_mbid), ("release-group", mb.release_group_mbid)):
            if not mbid:
                continue
            data = _http_bytes(f"https://coverartarchive.org/{kind}/{mbid}/front")
            if data and data[:2] == b"\xff\xd8":
                return data
    for p in fallback_paths:
        if p and os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    return None


# ── Audio: probe, convert, tag ─────────────────────────────────────────────
def ffprobe_tags(path: str) -> dict:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", path],
            text=True)
        return {k.lower(): v for k, v in (json.loads(out).get("format", {}).get("tags", {}) or {}).items()}
    except Exception:
        return {}


def needs_conversion(path: str) -> bool:
    return os.path.splitext(path)[1].lower() not in ZUNE_OK_EXT


def to_mp3(src: str, dst: str) -> bool:
    rc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-map", "0:a",
         "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-map_metadata", "0",
         "-id3v2_version", "3", dst],
        stderr=subprocess.DEVNULL).returncode
    return rc == 0 and os.path.isfile(dst)


def make_baseline_cover(data: bytes, dst: str, size: int = ART_SIZE) -> str | None:
    src = dst + ".orig"
    with open(src, "wb") as f:
        f.write(data)
    rc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-vf", f"scale={size}:{size}:flags=lanczos", "-pix_fmt", "yuvj420p", dst],
        stderr=subprocess.DEVNULL).returncode
    os.remove(src)
    return dst if rc == 0 and os.path.isfile(dst) else None


def write_id3(path: str, *, title, artist, album, track, total, year, genre,
              cover: bytes | None, artist_mbid: str | None):
    from mutagen.id3 import (ID3, ID3NoHeaderError, TIT2, TPE1, TPE2, TALB,
                             TRCK, TCON, TYER, TDRC, APIC, TXXX)
    try:
        t = ID3(path)
    except ID3NoHeaderError:
        t = ID3()
    t.delall("TIT2"); t.add(TIT2(encoding=3, text=title))
    t.delall("TPE1"); t.add(TPE1(encoding=3, text=artist))
    t.delall("TPE2"); t.add(TPE2(encoding=3, text=artist))
    t.delall("TALB"); t.add(TALB(encoding=3, text=album))
    trk = f"{track}/{total}" if total else str(track)
    t.delall("TRCK"); t.add(TRCK(encoding=3, text=trk))
    if genre:
        t.delall("TCON"); t.add(TCON(encoding=3, text=genre))
    if year:
        t.delall("TYER"); t.add(TYER(encoding=3, text=str(year)))
        t.delall("TDRC"); t.add(TDRC(encoding=3, text=str(year)))
    if cover:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    if artist_mbid:
        t.delall("TXXX:MusicBrainz Artist Id")
        t.add(TXXX(encoding=3, desc="MusicBrainz Artist Id", text=artist_mbid))
    t.save(path, v2_version=3)


def find_audio(folder: str) -> list[str]:
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in AUDIO_EXT:
                out.append(os.path.join(root, f))
    return sorted(out)


def most_common(vals):
    vals = [v for v in vals if v]
    if not vals:
        return ""
    return max(set(vals), key=vals.count)
