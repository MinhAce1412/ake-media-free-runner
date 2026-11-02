#!/usr/bin/env bash
set -euo pipefail
URL="${1:?public media URL required}"
ID="${2:?stable content id required}"
DIRECT_MEDIA_URL="${3:-}"
START="${4:-0}"
END="${5:-0}"
EXPECTED_DURATION="${6:-0}"

rm -rf output/deep work/deep
mkdir -p output/deep work/deep

case "$URL" in
  https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*|https://www.tiktok.com/*|https://tiktok.com/*|https://www.facebook.com/*|https://facebook.com/*|https://fb.watch/*) ;;
  *) echo "Unsupported/unsafe source host: $URL" >&2; exit 20 ;;
esac

ACQUISITION="platform_direct"
ANALYSIS_START="$START"
ANALYSIS_END="$END"
SOURCE_DURATION="0"

if [[ -n "$DIRECT_MEDIA_URL" ]]; then
  case "$DIRECT_MEDIA_URL" in
    https://storage.googleapis.com/vidiq-user-videos/*) ;;
    *) echo "Unsupported bridge media host" >&2; exit 21 ;;
  esac

  SOURCE_DURATION="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$DIRECT_MEDIA_URL" | head -n1 || true)"
  python - "$EXPECTED_DURATION" "$SOURCE_DURATION" > output/deep/media_identity.json <<'PY'
import json,sys
try: expected=float(sys.argv[1] or 0)
except: expected=0.0
try: actual=float(sys.argv[2] or 0)
except: actual=0.0
tol=max(3.0, expected*0.002) if expected>0 else None
diff=abs(actual-expected) if expected>0 and actual>0 else None
status='NOT_CHECKED' if expected<=0 else ('PASS' if actual>0 and diff<=tol else 'FAIL')
print(json.dumps({'expected_duration_sec':expected,'actual_duration_sec':actual,'difference_sec':diff,'tolerance_sec':tol,'status':status,'rule':'FAIL_CLOSED when expected duration is supplied and bridge media duration mismatches.'},ensure_ascii=False))
if expected>0 and status!='PASS': sys.exit(31)
PY

  if python - "$START" "$END" <<'PY'
import sys
s=float(sys.argv[1] or 0); e=float(sys.argv[2] or 0)
sys.exit(0 if e>s and e>0 else 1)
PY
  then
    ACQUISITION="vidiq_zero_credit_bridge_remote_window"
    WINDOW_DURATION="$(python - "$START" "$END" <<'PY'
import sys
print(max(0.1,float(sys.argv[2])-float(sys.argv[1])))
PY
)"
    ffmpeg -nostdin -loglevel error -y -ss "$START" -i "$DIRECT_MEDIA_URL" -t "$WINDOW_DURATION" \
      -map '0:v:0?' -map '0:a:0?' -c:v libx264 -preset ultrafast -crf 23 -c:a aac -b:a 128k -movflags +faststart \
      work/deep/source.mp4
    ANALYSIS_START="0"
    ANALYSIS_END="0"
    printf '%s\n' "{\"mode\":\"remote_window\",\"original_start\":$START,\"original_end\":$END,\"source_time_offset_sec\":$START,\"timestamp_rule\":\"source_time = local_analysis_time + source_time_offset_sec\"}" > output/deep/source_window.json
  else
    ACQUISITION="vidiq_zero_credit_bridge_full_media"
    curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 "$DIRECT_MEDIA_URL" -o work/deep/source.mp4
    printf '%s\n' "{\"mode\":\"full_media\",\"original_start\":$START,\"original_end\":$END,\"source_time_offset_sec\":0,\"timestamp_rule\":\"analysis uses original source timeline\"}" > output/deep/source_window.json
  fi
else
  yt-dlp --no-playlist --no-overwrites --restrict-filenames -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 -o 'work/deep/%(id)s.%(ext)s' "$URL"
  printf '%s\n' "{\"mode\":\"platform_direct\",\"original_start\":$START,\"original_end\":$END,\"source_time_offset_sec\":0,\"timestamp_rule\":\"analysis uses original source timeline\"}" > output/deep/source_window.json
  printf '%s\n' '{"status":"PLATFORM_DIRECT","rule":"Identity follows platform-direct acquisition; no bridge duration mapping required."}' > output/deep/media_identity.json
fi

MEDIA="$(find work/deep -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | head -n 1)"
[[ -n "${MEDIA:-}" && -s "$MEDIA" ]] || { echo 'No media file acquired' >&2; exit 22; }

ffprobe -v quiet -print_format json -show_format -show_streams "$MEDIA" > output/deep/ffprobe.json
printf '%s\n' "$ACQUISITION" > output/deep/acquisition.txt

ARGS=("$MEDIA" --content-id "$ID" --source-url "$URL" --out output/deep --start "$ANALYSIS_START")
if [[ "$ANALYSIS_END" != "0" && -n "$ANALYSIS_END" ]]; then ARGS+=(--end "$ANALYSIS_END"); fi
python scripts/deep_editor_analysis.py "${ARGS[@]}"
python scripts/refine_scene_evidence.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep
python scripts/refine_multimodal_evidence.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep
python scripts/asr_hallucination_guard.py --evidence output/deep/deep_evidence.json --out output/deep

CLAP_PYTHON="${AKE_CLAP_PYTHON:-}"
if [[ -n "$CLAP_PYTHON" && -x "$CLAP_PYTHON" ]]; then "$CLAP_PYTHON" scripts/clap_sfx_refine.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep || true; fi
[[ -s output/deep/clap_sfx_candidates.json ]] || printf '%s\n' '{"status":"unavailable","results":[],"rule":"Optional CLAP evidence unavailable; do not guess SFX."}' > output/deep/clap_sfx_candidates.json
python - <<'PY'
import json
p='output/deep/deep_evidence.json'; cp='output/deep/clap_sfx_candidates.json'; sw='output/deep/source_window.json'; mi='output/deep/media_identity.json'
d=json.load(open(p,encoding='utf-8')); c=json.load(open(cp,encoding='utf-8'))
d['clap_sfx_refined']={'status':c.get('status'),'tested_windows':len(c.get('results',[]) or []),'accepted_candidate_count':sum(1 for x in (c.get('results',[]) or []) if x.get('accepted_as_candidate')),'file':'clap_sfx_candidates.json','rule':'CLAP labels are semantic candidates only; exact SFX identity requires corroboration.'}
d['source_window']=json.load(open(sw,encoding='utf-8'))
d['media_identity']=json.load(open(mi,encoding='utf-8'))
json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
PY
SHAZAM_PYTHON="${AKE_SHAZAM_PYTHON:-}"
if [[ -n "$SHAZAM_PYTHON" && -x "$SHAZAM_PYTHON" ]]; then "$SHAZAM_PYTHON" scripts/music_candidate_id.py "$MEDIA" --evidence output/deep/deep_evidence.json --out output/deep || true; fi

[[ -s output/deep/deep_evidence.json ]] || exit 23
[[ -s output/deep/hook_contact_sheet.jpg ]] || exit 24
[[ -s output/deep/timeline_contact_sheet.jpg ]] || exit 25
[[ -s output/deep/scene_boundary_index.json ]] || exit 26
[[ -s output/deep/editor_timeline_evidence.json ]] || exit 27
[[ -s output/deep/transcript_refined.json ]] || exit 28
[[ -s output/deep/audio_sfx_refined.json ]] || exit 29
[[ -s output/deep/clap_sfx_candidates.json ]] || exit 30
[[ -s output/deep/music_identification.json ]] || printf '%s\n' '{"status":"UNKNOWN","track_name":"UNKNOWN","rule":"Music recognition unavailable; exact track remains UNKNOWN."}' > output/deep/music_identification.json
rm -rf work/deep
