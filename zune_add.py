#!/usr/bin/env python3
"""
zune-add — add an album folder to the Zune HD, automatically:
  * detects artist/album, looks up canonical metadata on MusicBrainz
  * fetches cover art (Cover Art Archive), embeds a Zune-friendly baseline JPEG
  * transcodes FLAC/OGG/etc -> MP3 320 (Zune HD can't play FLAC)
  * writes clean ID3v2.3 tags (+ MusicBrainz Artist Id)
  * resets USB / clears the gvfs auto-mounter, then uploads

Usage:
  zune_add.py <album-folder> [--replace] [--artist NAME] [--album NAME]
              [--genre G] [--no-online] [--dry-run] [--yes]
"""
import argparse
import os
import re
import sys
import tempfile

import zunelib as z


def detect_album(files):
    artists, albums, genres = [], [], []
    for f in files:
        t = z.ffprobe_tags(f)
        artists.append(t.get("album_artist") or t.get("artist", ""))
        albums.append(t.get("album", ""))
        genres.append(t.get("genre", ""))
    return z.most_common(artists), z.most_common(albums), z.most_common(genres)


def track_index(path, fallback):
    t = z.ffprobe_tags(path)
    m = re.match(r"\s*(\d+)", t.get("track", "") or "")
    if m:
        return int(m.group(1))
    m = re.match(r"\s*(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else fallback


def main():
    ap = argparse.ArgumentParser(description="Add an album to the Zune HD (automated).")
    ap.add_argument("folder")
    ap.add_argument("--artist", help="override detected album-artist")
    ap.add_argument("--album", help="override detected album title")
    ap.add_argument("--genre", help="override genre")
    ap.add_argument("--replace", action="store_true",
                    help="delete this artist from the device first (clean re-add)")
    ap.add_argument("--no-online", action="store_true", help="skip MusicBrainz lookup")
    ap.add_argument("--dry-run", action="store_true", help="prepare + show plan, don't upload")
    ap.add_argument("--yes", action="store_true", help="don't prompt for confirmation")
    args = ap.parse_args()

    folder = os.path.abspath(args.folder)
    files = z.find_audio(folder)
    if not files:
        sys.exit(f"No audio files found in {folder}")
    z.log(f"Found {len(files)} audio file(s) in {os.path.basename(folder)}")

    d_artist, d_album, d_genre = detect_album(files)
    artist = args.artist or d_artist or "Unknown Artist"
    album = args.album or d_album or os.path.basename(folder)
    genre = args.genre or d_genre or ""
    z.log(f"Detected: artist='{artist}'  album='{album}'  genre='{genre or '-'}'")

    # ── Online metadata ────────────────────────────────────────────────
    mb = None
    if not args.no_online:
        z.log("Looking up MusicBrainz…")
        mb = z.musicbrainz_lookup(artist, album, expected_tracks=len(files))
        if mb:
            z.log(f"  match: {mb.artist} — {mb.album} ({mb.date})  "
                  f"[{len(mb.tracks)} tracks]  mbid={mb.artist_mbid or '-'}")
            if mb.artist:
                artist = mb.artist
            if mb.album:
                album = mb.album
        else:
            z.log("  no MusicBrainz match — using file tags")

    year = (mb.date if mb else "") or (z.ffprobe_tags(files[0]).get("date", "")[:4])
    artist_mbid = mb.artist_mbid if mb else ""
    # Only trust MusicBrainz track titles when the matched edition has exactly
    # as many tracks as we have files (otherwise a deluxe/live/JP edition would
    # overwrite good titles with the wrong ones — keep the file's own title).
    use_mb_titles = bool(mb and len(mb.tracks) == len(files))
    mb_titles = {t["position"]: t["title"] for t in (mb.tracks if use_mb_titles else [])}
    if mb and not use_mb_titles:
        z.log(f"  (keeping file titles — MB edition has {len(mb.tracks)} tracks, you have {len(files)})")
    total = len(files)   # the album as the user has it (full-album uploads)

    # ── Cover art ──────────────────────────────────────────────────────
    fallbacks = []
    for name in ("cover.jpg", "folder.jpg", "Folder.jpg"):
        fallbacks.append(os.path.join(folder, name))
    cover_raw = z.fetch_cover(mb, fallbacks)
    stage = tempfile.mkdtemp(prefix="zune_add_")
    cover = None
    if cover_raw:
        cover = None
        made = z.make_baseline_cover(cover_raw, os.path.join(stage, "_cover.jpg"))
        if made:
            with open(made, "rb") as f:
                cover = f.read()
        z.log(f"Cover art: {'ok' if cover else 'FAILED'} ({len(cover_raw)//1024} KB source)")
    else:
        z.log("Cover art: none found")

    # ── Build track plan ───────────────────────────────────────────────
    plan = []
    for i, f in enumerate(sorted(files, key=lambda p: track_index(p, 999)), start=1):
        pos = track_index(f, i)
        tags = z.ffprobe_tags(f)
        title = mb_titles.get(pos) or tags.get("title") or os.path.splitext(os.path.basename(f))[0]
        plan.append({"src": f, "pos": pos, "title": title,
                     "convert": z.needs_conversion(f)})

    z.log("\n=== Proposed upload ===")
    z.log(f"  {artist} — {album} ({year or '?'}){'  [genre: '+genre+']' if genre else ''}")
    for p in plan:
        flag = "  (→mp3)" if p["convert"] else ""
        z.log(f"   {p['pos']:>2}. {p['title']}{flag}")
    if args.replace:
        z.log("  MODE: --replace (delete existing artist on device first)")

    if args.dry_run:
        z.log("\nDry run — staging then stopping (no device upload).")
    elif not args.yes:
        if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
            z.log("Aborted."); sys.exit(0)

    # ── Stage (convert + tag) ──────────────────────────────────────────
    z.log("\nStaging (convert + tag)…")
    for p in plan:
        base = f"{p['pos']:02d} - {re.sub(r'[/]', '_', p['title'])}.mp3"
        dst = os.path.join(stage, base)
        if p["convert"]:
            if not z.to_mp3(p["src"], dst):
                sys.exit(f"conversion failed: {p['src']}")
        else:
            import shutil
            shutil.copy2(p["src"], dst)
        z.write_id3(dst, title=p["title"], artist=artist, album=album,
                    track=p["pos"], total=total, year=year, genre=genre,
                    cover=cover, artist_mbid=artist_mbid)
    # remove staging cover helper so it isn't uploaded
    for junk in ("_cover.jpg",):
        jp = os.path.join(stage, junk)
        if os.path.exists(jp):
            os.remove(jp)
    z.log(f"  staged {len(plan)} tracks in {stage}")

    if args.dry_run:
        z.log(f"\nStaged at: {stage}  (inspect, then delete)")
        return

    # ── Device ─────────────────────────────────────────────────────────
    z.log("\nPreparing device…")
    if not z.prepare_device():
        sys.exit("Zune HD not ready (connect it and unlock the screen).")

    if args.replace:
        z.log(f"Deleting existing '{artist}' from device…")
        z.device_delete_artist(artist)
        z.prepare_device()

    z.log("Uploading…")
    rc, out = z.device_upload(stage, timeout=900)
    tail = "\n".join(l for l in out.splitlines()
                     if re.search(r"Upload Complete|Tracks:|error|denied|fail", l, re.I))
    z.log(tail or out[-800:])

    if rc == 0:
        # If the artist already existed, the uploader made a 2nd artist object.
        # Safely merge (re-point tracks to the original, then drop the empty
        # duplicate) — never deletes music.
        z.log("Consolidating artist (merge any duplicate)…")
        mrc, mout = z.device_merge_artist(artist)
        for line in mout.splitlines():
            if re.search(r"keeper|re-pointed|nothing to merge|duplicate", line, re.I):
                z.log("  " + line.strip())
    z.log("\n✓ Done." if rc == 0 else f"\n✗ Upload exited {rc}")


if __name__ == "__main__":
    main()
