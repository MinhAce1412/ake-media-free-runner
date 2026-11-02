#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"

rm -rf output work
mkdir -p output/frames output/subtitles work/media

# Safety: public/authorized media only. Never pass cookies, browser profiles,
# credentials, CAPTCHA/DRM bypass arguments, or private URLs here.
case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*)
    ;;
  *)
    echo "Unsupported/unsafe host for this runner: $URL" >&2
    exit 10
    ;;
esac

# Analysis copy only: cap resolution to 1080p to reduce bandwidth/runtime.
# A failure remains a failure; do not bypass host access controls.
yt-dlp --no-playlist --no-overwrites --restrict-filenames \
  --write-info-json --write-auto-subs --write-subs --sub-langs 'vi.*,en.*' \
  --convert-subs srt \
  -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 \
  -o 'work/media/%(id)s.%(ext)s' "$URL"

MEDIA="$(find work/media -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | head -n 1)"
INFO="$(find work/media -maxdepth 1 -type f -name '*.info.json' | head -n 1)"
[[ -n "${MEDIA:-}" && -s "$MEDIA" ]] || { echo 'No media file downloaded' >&2; exit 11; }
[[ -n "${INFO:-}" && -s "$INFO" ]] || { echo 'No metadata JSON produced' >&2; exit 12; }

cp "$INFO" output/info.json
ffprobe -v quiet -print_format json -show_format -show_streams "$MEDIA" > output/ffprobe.json
DUR="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$MEDIA")"
python scripts/make_frame_times.py "$DUR" > output/frame_times.txt

COUNT=0
while read -r T; do
  COUNT=$((COUNT+1))
  printf -v IDX '%02d' "$COUNT"
  ffmpeg -nostdin -loglevel error -ss "$T" -i "$MEDIA" -frames:v 1 -q:v 2 "output/frames/frame_${IDX}.jpg"
done < output/frame_times.txt

FRAME_COUNT="$(find output/frames -maxdepth 1 -type f -name 'frame_*.jpg' | wc -l | tr -d ' ')"
[[ "$FRAME_COUNT" -eq 12 ]] || { echo "Expected 12 frames, got $FRAME_COUNT" >&2; exit 13; }

# Deterministic 4x3 contact sheet in chronological frame order.
ffmpeg -nostdin -loglevel error -framerate 1 -i 'output/frames/frame_%02d.jpg' \
  -vf 'scale=360:-1,tile=4x3:padding=4:margin=4' -frames:v 1 output/contact_sheet.jpg
[[ -s output/contact_sheet.jpg ]] || { echo 'Contact sheet generation failed' >&2; exit 14; }

find work/media -maxdepth 1 -type f \( -name '*.srt' -o -name '*.vtt' \) -exec cp {} output/subtitles/ \; || true

TITLE="$(jq -r '.title // ""' output/info.json)"
UPLOADER="$(jq -r '.uploader // .channel // ""' output/info.json)"
UPLOAD_DATE="$(jq -r '.upload_date // ""' output/info.json)"
WEBPAGE_URL="$(jq -r '.webpage_url // .original_url // ""' output/info.json)"
WIDTH="$(jq -r '[.streams[]? | select(.codec_type=="video") | .width] | max // 0' output/ffprobe.json)"
HEIGHT="$(jq -r '[.streams[]? | select(.codec_type=="video") | .height] | max // 0' output/ffprobe.json)"
SUB_COUNT="$(find output/subtitles -maxdepth 1 -type f | wc -l | tr -d ' ')"

jq -n \
  --arg content_id "$ID" --arg requested_url "$URL" --arg webpage_url "$WEBPAGE_URL" \
  --arg title "$TITLE" --arg uploader "$UPLOADER" --arg upload_date "$UPLOAD_DATE" \
  --arg duration "$DUR" --argjson width "$WIDTH" --argjson height "$HEIGHT" \
  --argjson frame_count "$FRAME_COUNT" --argjson subtitle_file_count "$SUB_COUNT" \
  '{content_id:$content_id,requested_url:$requested_url,webpage_url:$webpage_url,title:$title,uploader:$uploader,upload_date:$upload_date,duration_seconds:($duration|tonumber),analysis_copy:{width:$width,height:$height},frame_count:$frame_count,subtitle_file_count:$subtitle_file_count,evidence_level:"VISUAL_FRAMES_READY",visual_claim_policy:"Frame/contact-sheet observations are allowed only after those image files are actually inspected by the consuming runtime. Audio/editing claims still require subtitle/transcript/audio evidence.",note:"The source media is used transiently during the run and is intentionally excluded from the artifact."}' > output/ake_evidence.json

# Avoid storing/re-uploading third-party source media as an artifact.
rm -rf work
