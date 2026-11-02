#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"
DIRECT_MEDIA_URL="${3:-}"

rm -rf output work
mkdir -p output/frames output/subtitles work/media

case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*)
    ;;
  *)
    echo "Unsupported/unsafe source host: $URL" >&2
    exit 10
    ;;
esac

ACQUISITION="platform_direct"
if [[ -n "$DIRECT_MEDIA_URL" ]]; then
  case "$DIRECT_MEDIA_URL" in
    https://storage.googleapis.com/vidiq-user-videos/*)
      ;;
    *)
      echo "Unsupported bridge media host" >&2
      exit 15
      ;;
  esac
  ACQUISITION="vidiq_zero_credit_bridge"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 180 \
    "$DIRECT_MEDIA_URL" -o work/media/source.mp4
  jq -n --arg webpage_url "$URL" --arg acquisition "$ACQUISITION" \
    '{webpage_url:$webpage_url,original_url:$webpage_url,acquisition:$acquisition}' > work/media/source.info.json
else
  # Direct public fetch only. Never add cookies, accounts, CAPTCHA/DRM bypasses.
  yt-dlp --no-playlist --no-overwrites --restrict-filenames \
    --write-info-json --write-auto-subs --write-subs --sub-langs 'vi.*,en.*' \
    --convert-subs srt \
    -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 \
    -o 'work/media/%(id)s.%(ext)s' "$URL"
fi

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
  --arg acquisition "$ACQUISITION" --arg duration "$DUR" \
  --argjson width "$WIDTH" --argjson height "$HEIGHT" \
  --argjson frame_count "$FRAME_COUNT" --argjson subtitle_file_count "$SUB_COUNT" \
  '{content_id:$content_id,requested_url:$requested_url,webpage_url:$webpage_url,title:$title,uploader:$uploader,upload_date:$upload_date,acquisition:$acquisition,duration_seconds:($duration|tonumber),analysis_copy:{width:$width,height:$height},frame_count:$frame_count,subtitle_file_count:$subtitle_file_count,evidence_level:"VISUAL_FRAMES_READY",visual_claim_policy:"Frame/contact-sheet observations are allowed only after those image files are actually inspected by the consuming runtime. Audio/editing claims still require subtitle/transcript/audio evidence.",note:"Source media is transient and excluded from the artifact."}' > output/ake_evidence.json

rm -rf work
