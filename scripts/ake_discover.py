#!/usr/bin/env python3
"""Ake free public YouTube RSS discovery / guarded one-video FAST intake.

Only public feed metadata is permanent. Never calls paid services, logs in, or
promotes machine evidence to TRAINING_APPROVED. Video acquisition, when usable,
is delegated to the repo's existing guarded public-media script.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

UTC = dt.timezone.utc
YT = "http://www.youtube.com/xml/schemas/2015"
ATOM = "http://www.w3.org/2005/Atom"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
MAX_SAVED = 1200
MAX_AGE_DAYS = 90

def now():
    return dt.datetime.now(UTC)

def iso(time):
    return time.isoformat(timespec="seconds").replace("+00:00", "Z")

def load(path, default):
    p = pathlib.Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def save(path, value):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)

def parse_feed(xml_bytes, expected_channel):
    root = ET.fromstring(xml_bytes)
    result = []
    channel = root.findtext(f"{{{YT}}}channelId")
    if channel and channel != expected_channel:
        raise ValueError("Feed channel identity mismatch")
    for entry in root.findall(f"{{{ATOM}}}entry"):
        video_id = entry.findtext(f"{{{YT}}}videoId")
        entry_channel = entry.findtext(f"{{{YT}}}channelId")
        if not video_id or not VIDEO_ID.fullmatch(video_id):
            continue
        if entry_channel and entry_channel != expected_channel:
            continue
        published = entry.findtext(f"{{{ATOM}}}published", "")
        title = entry.findtext(f"{{{ATOM}}}title", "")
        try:
            published_date = dt.datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if published_date > now() + dt.timedelta(minutes=5):
            continue
        result.append({
            "video_id": video_id, "content_key": f"youtube:{video_id}",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published_at": iso(published_date), "title": title[:250],
            "source_channel_id": expected_channel,
        })
    return result

def discover(config_path, state_path, selection_path):
    config = load(config_path, {})
    channels = config.get("channels", [])
    state = load(state_path, {"schema_version": 1, "sources": {}, "videos": []})
    if state.get("schema_version") != 1:
        raise ValueError("Unrecognized state schema")
    videos = {v["video_id"]: v for v in state.get("videos", []) if VIDEO_ID.fullmatch(v.get("video_id", ""))}
    cutoff = now() - dt.timedelta(days=MAX_AGE_DAYS)
    added = 0
    for source in channels:
        channel = source.get("channel_id", "")
        if not CHANNEL_ID.fullmatch(channel):
            raise ValueError(f"Invalid channel ID: {channel[:30]}")
        health = state.setdefault("sources", {}).setdefault(channel, {})
        health.update({"name": source.get("name", ""), "last_attempt_at": iso(now())})
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AkeResearchBot/1.0 (public RSS metadata)"})
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read(1024 * 1024)
            entries = parse_feed(raw, channel)
            fresh = 0
            for v in entries:
                when = dt.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
                if when < cutoff:
                    continue
                if v["video_id"] not in videos:
                    videos[v["video_id"]] = {
                        **v, "creator_name": source.get("name", ""),
                        "first_seen_at": iso(now()), "evidence_level": "METADATA_ONLY",
                        "fast_status": "PENDING", "training_status": "NOT_APPROVED",
                        "fast_attempts": 0,
                    }
                    added += 1
                    fresh += 1
            health.update({"status": "PUBLIC_RSS_READ", "last_success_at": iso(now()), "items_seen": len(entries), "new_items": fresh})
            health.pop("error_type", None)
        except (OSError, ET.ParseError, ValueError) as err:
            health.update({"status": "SOURCE_UNAVAILABLE", "error_type": type(err).__name__, "error_detail": str(err)[:160]})
    state["videos"] = sorted(videos.values(), key=lambda v: (v["published_at"], v["video_id"]), reverse=True)[:MAX_SAVED]
    state.update({"updated_at": iso(now()), "new_this_run": added, "scope": "public YouTube RSS monitored sources; NOT a TikTok/FC Online market census"})
    available = [v for v in state["videos"] if v.get("fast_status") == "PENDING"]
    selected = available[0] if available else None
    selection = {"has_candidate": bool(selected), "content_key": selected["content_key"] if selected else None,
                 "url": selected["url"] if selected else None,
                 "added": added, "source_count": len(channels),
                 "fast_status": "PENDING" if selected else "NO_CANDIDATE"}
    save(state_path, state)
    save(selection_path, selection)
    print(json.dumps(selection, ensure_ascii=False))

def subprocess_json(args, max_seconds):
    return subprocess.run(args, text=True, capture_output=True, timeout=max_seconds, check=False)

def fast(state_path, selection_path, outcome_path):
    state = load(state_path, {})
    selection = load(selection_path, {})
    if not selection.get("has_candidate"):
        save(outcome_path, {"status": "NO_CANDIDATE"})
        return
    key = selection["content_key"]
    item = next((v for v in state.get("videos", []) if v.get("content_key") == key), None)
    if not item or item.get("fast_status") != "PENDING":
        raise ValueError("Selected candidate missing or already attempted")
    outcome = "SOURCE_BLOCKED"
    evidence = "METADATA_ONLY"
    reason = "DIRECT_PUBLIC_FETCH_FAILED"
    try:
        info = subprocess_json([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--skip-download", "--dump-single-json", "--no-warnings", item["url"]], 110)
        if info.returncode != 0:
            reason = "METADATA_SOURCE_UNAVAILABLE"
        else:
            data = json.loads(info.stdout)
            if data.get("id") != item["video_id"]:
                reason = "MEDIA_IDENTITY_MISMATCH"
            elif not isinstance(data.get("duration"), (int, float)) or data["duration"] <= 0:
                reason = "DURATION_UNVERIFIED"
            elif data["duration"] > 180:
                outcome = "LONGFORM_PENDING_INDEX"
                reason = "VIDEO_OVER_180_SECONDS_REQUIRES_SELECTIVE_WINDOW"
            else:
                run = subprocess_json(["bash", "scripts/analyze_public_media.sh", item["url"], key.replace(":", "-"), ""], 900)
                manifest = pathlib.Path("output/ake_evidence.json")
                contact = pathlib.Path("output/contact_sheet.jpg")
                if run.returncode == 0 and manifest.exists() and contact.is_file() and contact.stat().st_size > 0:
                    d = json.loads(manifest.read_text(encoding="utf-8"))
                    if (d.get("content_id") == key.replace(":", "-") and d.get("requested_url") == item["url"] and
                        d.get("frame_count") == 12 and d.get("evidence_level") == "VISUAL_FRAMES_READY"):
                        outcome = "FAST_EVIDENCE_READY"
                        evidence = "VISUAL_FRAMES_READY_UNINSPECTED"
                        reason = "NEEDS_EDITOR_VISUAL_AUDIO_REVIEW"
                    else:
                        reason = "FAST_EVIDENCE_IDENTITY_OR_COMPLETENESS_FAIL"
                else:
                    reason = "FAST_ACQUISITION_OR_FRAME_FAILURE"
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        reason = "FAST_EXCEPTION_" + type(err).__name__
    item.update({"fast_status": outcome, "evidence_level": evidence, "fast_attempts": item.get("fast_attempts", 0) + 1,
                 "fast_last_attempt_at": iso(now()), "fast_reason": reason, "training_status": "NOT_APPROVED",
                 "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "")})
    state["updated_at"] = iso(now())
    save(state_path, state)
    outcome_record = {"content_key": key, "status": outcome, "reason": reason, "evidence_level": evidence,
                      "training_status": "NOT_APPROVED", "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "")}
    save(outcome_path, outcome_record)
    print(json.dumps(outcome_record, ensure_ascii=False))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["discover", "fast"])
    ap.add_argument("--config", default="config/ake_youtube_sources.json")
    ap.add_argument("--state", default="data/ake_discovery_state.json")
    ap.add_argument("--selection", default="output/ake_selection.json")
    ap.add_argument("--outcome", default="output/ake_fast_outcome.json")
    a = ap.parse_args()
    if a.command == "discover":
        discover(a.config, a.state, a.selection)
    else:
        fast(a.state, a.selection, a.outcome)
