#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"
DIRECT_MEDIA_URL="${3:-}"
MAX_WINDOWS="${4:-20}"
EXPECTED_DURATION="${5:-0}"
rm -rf output/longform work/longform
mkdir -p output/longform work/longform
case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*) ;;
  *) echo "Unsupported/unsafe source host: $URL" >&2; exit 20 ;;
esac
ACQUISITION="platform_direct"
if [[ -n "$DIRECT_MEDIA_URL" ]]; then
  case "$DIRECT_MEDIA_URL" in https://storage.googleapis.com/vidiq-user-videos/*) ;; *) echo "Unsupported bridge media host" >&2; exit 21 ;; esac
  ACTUAL_DURATION="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$DIRECT_MEDIA_URL" | head -n1 || true)"
  python - "$EXPECTED_DURATION" "$ACTUAL_DURATION" > output/longform/media_identity.json <<'PY'
import json,sys
try: expected=float(sys.argv[1] or 0)
except: expected=0.0
try: actual=float(sys.argv[2] or 0)
except: actual=0.0
tol=max(3.0,expected*0.002) if expected>0 else None
diff=abs(actual-expected) if expected>0 and actual>0 else None
status='NOT_CHECKED' if expected<=0 else ('PASS' if actual>0 and diff<=tol else 'FAIL')
print(json.dumps({'expected_duration_sec':expected,'actual_duration_sec':actual,'difference_sec':diff,'tolerance_sec':tol,'status':status,'rule':'FAIL_CLOSED when expected duration is supplied and bridge media duration mismatches.'},ensure_ascii=False))
if expected>0 and status!='PASS': sys.exit(31)
PY
  ACQUISITION="vidiq_zero_credit_bridge"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 "$DIRECT_MEDIA_URL" -o work/longform/source.mp4
else
  yt-dlp --no-playlist --no-overwrites --restrict-filenames -f 'bv*[height<=720]+ba/b[height<=720]/b' --merge-output-format mp4 -o 'work/longform/%(id)s.%(ext)s' "$URL"
  printf '%s\n' '{"status":"PLATFORM_DIRECT","rule":"Identity follows platform-direct acquisition; no bridge duration mapping required."}' > output/longform/media_identity.json
fi
MEDIA="$(find work/longform -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | head -n 1)"
[[ -n "${MEDIA:-}" && -s "$MEDIA" ]] || { echo 'No media file acquired' >&2; exit 22; }
printf '%s\n' "$ACQUISITION" > output/longform/acquisition.txt
ffprobe -v quiet -print_format json -show_format -show_streams "$MEDIA" > output/longform/ffprobe.json
python scripts/longform_index.py "$MEDIA" --content-id "$ID" --source-url "$URL" --out output/longform --max-windows "$MAX_WINDOWS"
[[ -s output/longform/longform_index.json ]] || exit 23
[[ -s output/longform/candidate_windows.json ]] || exit 24
[[ -s output/longform/longform_contact_sheet.jpg ]] || exit 25
rm -rf work/longform
