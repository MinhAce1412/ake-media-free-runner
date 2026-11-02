#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"
DIRECT_MEDIA_URL="${3:-}"
MAX_WINDOWS="${4:-20}"
rm -rf output/longform work/longform
mkdir -p output/longform work/longform
case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*) ;;
  *) echo "Unsupported/unsafe source host: $URL" >&2; exit 20 ;;
esac
ACQUISITION="platform_direct"
if [[ -n "$DIRECT_MEDIA_URL" ]]; then
  case "$DIRECT_MEDIA_URL" in
    https://storage.googleapis.com/vidiq-user-videos/*) ;;
    *) echo "Unsupported bridge media host" >&2; exit 21 ;;
  esac
  ACQUISITION="vidiq_zero_credit_bridge"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 "$DIRECT_MEDIA_URL" -o work/longform/source.mp4
else
  yt-dlp --no-playlist --no-overwrites --restrict-filenames -f 'bv*[height<=720]+ba/b[height<=720]/b' --merge-output-format mp4 -o 'work/longform/%(id)s.%(ext)s' "$URL"
fi
MEDIA="$(find work/longform -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | head -n 1)"
[[ -n "${MEDIA:-}" && -s "$MEDIA" ]] || { echo 'No media file acquired' >&2; exit 22; }
printf '%s\n' "$ACQUISITION" > output/longform/acquisition.txt
ffprobe -v quiet -print_format json -show_format -show_streams "$MEDIA" > output/longform/ffprobe.json
python scripts/longform_index.py "$MEDIA" --content-id "$ID" --source-url "$URL" --out output/longform --max-windows "$MAX_WINDOWS"
[[ -s output/longform/longform_index.json ]] || { echo 'longform_index.json missing' >&2; exit 23; }
[[ -s output/longform/candidate_windows.json ]] || { echo 'candidate_windows.json missing' >&2; exit 24; }
[[ -s output/longform/longform_contact_sheet.jpg ]] || { echo 'longform contact sheet missing' >&2; exit 25; }
rm -rf work/longform
