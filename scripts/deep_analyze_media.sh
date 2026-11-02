#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"
DIRECT_MEDIA_URL="${3:-}"
START="${4:-0}"
END="${5:-0}"

rm -rf output/deep work/deep
mkdir -p output/deep work/deep

case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*)
    ;;
  *) echo "Unsupported/unsafe source host: $URL" >&2; exit 20 ;;
esac

ACQUISITION="platform_direct"
if [[ -n "$DIRECT_MEDIA_URL" ]]; then
  case "$DIRECT_MEDIA_URL" in
    https://storage.googleapis.com/vidiq-user-videos/*) ;;
    *) echo "Unsupported bridge media host" >&2; exit 21 ;;
  esac
  ACQUISITION="vidiq_zero_credit_bridge"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 240 "$DIRECT_MEDIA_URL" -o work/deep/source.mp4
else
  yt-dlp --no-playlist --no-overwrites --restrict-filenames \
    -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 \
    -o 'work/deep/%(id)s.%(ext)s' "$URL"
fi

MEDIA="$(find work/deep -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | head -n 1)"
[[ -n "${MEDIA:-}" && -s "$MEDIA" ]] || { echo 'No media file acquired' >&2; exit 22; }

ffprobe -v quiet -print_format json -show_format -show_streams "$MEDIA" > output/deep/ffprobe.json
printf '%s\n' "$ACQUISITION" > output/deep/acquisition.txt

ARGS=("$MEDIA" --content-id "$ID" --source-url "$URL" --out output/deep --start "$START")
if [[ "$END" != "0" && -n "$END" ]]; then
  ARGS+=(--end "$END")
fi
python scripts/deep_editor_analysis.py "${ARGS[@]}"
python scripts/refine_scene_evidence.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep
# Best-effort only: a ShazamIO hit is an external candidate, never an automatically verified track.
python scripts/music_candidate_id.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep || true

[[ -s output/deep/deep_evidence.json ]] || { echo 'deep_evidence.json missing' >&2; exit 23; }
[[ -s output/deep/hook_contact_sheet.jpg ]] || { echo 'hook contact sheet missing' >&2; exit 24; }
[[ -s output/deep/timeline_contact_sheet.jpg ]] || { echo 'timeline contact sheet missing' >&2; exit 25; }
[[ -s output/deep/scene_boundary_index.json ]] || { echo 'scene boundary index missing' >&2; exit 26; }
[[ -s output/deep/music_identification.json ]] || printf '%s\n' '{"status":"UNKNOWN","track_name":"UNKNOWN","rule":"Music recognition did not run; exact track remains UNKNOWN."}' > output/deep/music_identification.json

# Source media is transient. Never upload it as an artifact.
rm -rf work/deep
