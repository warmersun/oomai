"""
YouTube transcript fetcher using yt-dlp.

Fetches transcripts (subtitles) from recent YouTube videos on a given channel.
Used by the batch processing system to ingest YouTube content into the knowledge graph.
"""
import asyncio
import glob
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone

import yt_dlp

logger = logging.getLogger("kg_batch")


def _parse_json3_transcript(filepath: str) -> str:
    """Parse a json3 subtitle file into plain text."""
    import json as _json
    with open(filepath, "r", encoding="utf-8") as f:
        data = _json.load(f)

    segments = []
    for event in data.get("events", []):
        # Each event has "segs" with text fragments
        segs = event.get("segs", [])
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if text and text != "\n":
            segments.append(text)

    # Deduplicate — auto-subs repeat segments
    deduped = []
    for seg in segments:
        if not deduped or seg != deduped[-1]:
            deduped.append(seg)

    return " ".join(deduped)


def _strip_vtt_tags(text: str) -> str:
    """Remove VTT formatting tags and metadata, returning plain text."""
    # Remove VTT header
    text = re.sub(r"WEBVTT.*?\n\n", "", text, count=1, flags=re.DOTALL)
    # Split into cue blocks (separated by blank lines)
    blocks = re.split(r"\n\n+", text.strip())

    lines_seen = []
    for block in blocks:
        block_lines = block.strip().split("\n")
        for line in block_lines:
            # Skip timestamp lines
            if re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->", line):
                continue
            # Skip sequence numbers
            if re.match(r"^\d+$", line.strip()):
                continue
            # Remove HTML-like tags
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean and (not lines_seen or clean != lines_seen[-1]):
                lines_seen.append(clean)

    return " ".join(lines_seen)


# Maximum transcript characters to send to the LLM (roughly ~12K tokens)
MAX_TRANSCRIPT_CHARS = 50_000


def _fetch_transcripts_sync(channel_url: str, hours_back: int = 24) -> list[dict]:
    """
    Synchronous function that uses yt-dlp to:
    1. List recent videos from a YouTube channel
    2. Download transcripts for videos uploaded within the last `hours_back` hours

    Returns a list of dicts with keys: title, url, upload_date, transcript
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_str = cutoff.strftime("%Y%m%d")  # yt-dlp dateafter format: YYYYMMDD

    # Ensure we target the /videos tab directly, not the channel root
    # (channel root returns tabs like Videos, Live, Shorts as entries)
    videos_url = channel_url.rstrip("/")
    if not videos_url.endswith("/videos"):
        videos_url += "/videos"

    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: List recent videos from the channel's videos tab
        list_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",  # list video entries without downloading
            "playlistend": 20,  # check last 20 videos max
        }

        try:
            with yt_dlp.YoutubeDL(list_opts) as ydl:
                info = ydl.extract_info(videos_url, download=False)
        except Exception as e:
            logger.error(f"Failed to list videos from {videos_url}: {e}")
            return []

        if not info:
            return []

        entries = info.get("entries", [])
        if not entries:
            logger.info(f"No videos found on channel: {videos_url}")
            return []

        # Step 2: For each video, check date and download transcript
        for entry in entries:
            if not entry:
                continue

            video_id = entry.get("id", "")
            video_url = entry.get("url", "")
            video_title = entry.get("title", "Unknown")

            # Skip non-video entries (tabs, playlists, etc.)
            if not video_id or len(video_id) != 11:
                logger.info(f"Skipping non-video entry: '{video_title}'")
                continue

            if not video_url or "watch?v=" not in video_url:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Step 2a: Get full metadata to check upload date
            meta_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            }

            try:
                with yt_dlp.YoutubeDL(meta_opts) as ydl:
                    video_info = ydl.extract_info(video_url, download=False)
            except Exception as e:
                logger.warning(f"Failed to get metadata for {video_title}: {e}")
                continue

            if not video_info:
                continue

            upload_date = video_info.get("upload_date", "")  # YYYYMMDD
            if not upload_date or upload_date < cutoff_str:
                logger.info(f"Skipping '{video_title}' — uploaded {upload_date}, before cutoff {cutoff_str}")
                continue

            # Step 2b: Download subtitles for this video (prefer json3 for cleaner parsing)
            sub_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en"],
                "subtitlesformat": "json3/vtt/best",
                "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            }

            try:
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    ydl.download([video_url])
            except Exception as e:
                logger.warning(f"Failed to download subtitles for '{video_title}': {e}")
                continue

            # Step 2c: Read the subtitle file (try json3 first, then vtt)
            vid = video_info.get("id", "")

            json3_files = glob.glob(os.path.join(tmpdir, f"{vid}*.json3"))
            vtt_files = glob.glob(os.path.join(tmpdir, f"{vid}*.vtt"))

            transcript = ""
            if json3_files:
                transcript = _parse_json3_transcript(json3_files[0])
            elif vtt_files:
                with open(vtt_files[0], "r", encoding="utf-8") as f:
                    raw_transcript = f.read()
                transcript = _strip_vtt_tags(raw_transcript)

            if not transcript.strip():
                logger.warning(f"Empty transcript for '{video_title}'")
                continue

            # Cap transcript size to avoid overwhelming the LLM
            if len(transcript) > MAX_TRANSCRIPT_CHARS:
                logger.info(f"Truncating transcript for '{video_title}' from {len(transcript)} to {MAX_TRANSCRIPT_CHARS} chars")
                transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[... transcript truncated ...]"

            results.append({
                "title": video_title,
                "url": video_url,
                "upload_date": upload_date,
                "transcript": transcript,
            })

            logger.info(f"✅ Got transcript for '{video_title}' ({len(transcript)} chars)")

    return results


async def fetch_recent_transcripts(channel_url: str, hours_back: int = 24) -> list[dict]:
    """
    Async wrapper around the synchronous yt-dlp transcript fetcher.
    Runs in a thread executor to avoid blocking the event loop.

    Args:
        channel_url: YouTube channel URL (e.g., https://www.youtube.com/@channelname)
        hours_back: How many hours back to look for new videos (default: 24)

    Returns:
        List of dicts with keys: title, url, upload_date, transcript
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_transcripts_sync, channel_url, hours_back)
