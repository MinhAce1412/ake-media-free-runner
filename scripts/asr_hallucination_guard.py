#!/usr/bin/env python3
import argparse, json
from pathlib import Path


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def dump(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def overlap(a,b,c,d):
    return max(a,c) < min(b,d)


def quality_from_segments(segs, duration):
    speech=sum(max(0.0,float(s.get('end',0))-float(s.get('start',0))) for s in segs)
    chars=sum(len(''.join(str(s.get('text','')).split())) for s in segs)
    return {'chars':chars,'speech_seconds':round(speech,3),'coverage':round(min(1.0,speech/max(duration,1e-9)),3)}


def normalize_legacy(legacy):
    out=[]
    for s in legacy.get('segments',[]) or []:
        text=str(s.get('text','')).strip()
        if not text: continue
        out.append({
            'start':round(float(s.get('start',0)),3),
            'end':round(float(s.get('end',0)),3),
            'text':text,
            'words':s.get('words',[]),
            'source':'WHISPER_VAD_SAFE_FALLBACK'
        })
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',required=True)
    ap.add_argument('--evidence',required=True)
    args=ap.parse_args(); out=Path(args.out)

    refined=load(out/'transcript_refined.json',{})
    audio=load(out/'audio_sfx_refined.json',{})
    legacy=load(out/'transcript.json',{})
    deep=load(args.evidence,{})
    duration=float((deep.get('range') or {}).get('duration') or 0)

    selected_cov=float((refined.get('quality') or {}).get('coverage') or 0)
    speech_cov=float((audio.get('speech_presence') or {}).get('coverage_score_ge_0_3') or 0)
    music_cov=float((audio.get('music_presence') or {}).get('coverage_score_ge_0_5') or 0)
    legacy_segs=normalize_legacy(legacy)
    legacy_q=quality_from_segments(legacy_segs,duration)

    # Independent guard: a transcript claiming speech over most of a strongly musical clip
    # is suspicious when YAMNet sees little speech. Prefer the conservative VAD transcript.
    mismatch = selected_cov >= 0.45 and speech_cov <= 0.18 and selected_cov >= max(0.45, speech_cov*3.0)
    strong_music = music_cov >= 0.65
    triggered=bool(mismatch and strong_music and legacy_segs)

    refined['hallucination_guard']={
        'triggered':triggered,
        'selected_asr_coverage_before':round(selected_cov,3),
        'independent_speech_coverage':round(speech_cov,3),
        'independent_music_coverage':round(music_cov,3),
        'legacy_vad_coverage':legacy_q['coverage'],
        'rule':'If ASR claims broad speech while independent audio evidence shows strongly dominant music and little speech, prefer conservative VAD transcript and label uncertain wording.'
    }
    if triggered:
        refined['segments']=legacy_segs
        refined['quality']=legacy_q
        refined['selected_pass']='vad_safe_fallback_after_hallucination_guard'
        refined['warning']='Broad no-VAD transcript was rejected as likely hallucination. Remaining text is conservative machine ASR and still must not be quoted as exact proper nouns without verification.'
    dump(out/'transcript_refined.json',refined)
    with open(out/'transcript_refined.txt','w',encoding='utf-8') as f:
        for s in refined.get('segments',[]):
            f.write(f"[{float(s['start']):07.3f}-{float(s['end']):07.3f}] {s['text']}\n")

    # Rebuild transcript assignments in the existing editor evidence timeline.
    timeline=load(out/'editor_timeline_evidence.json',{})
    for seg in timeline.get('segments',[]) or []:
        st=float(seg['start']); en=float(seg['end'])
        seg['transcript']=[s for s in refined.get('segments',[]) if overlap(st,en,float(s['start']),float(s['end']))]
    timeline['asr_hallucination_guard']=refined.get('hallucination_guard')
    dump(out/'editor_timeline_evidence.json',timeline)

    deep['transcript_refined']={
        'status':refined.get('status'),
        'quality':refined.get('quality'),
        'selected_pass':refined.get('selected_pass'),
        'hallucination_guard':refined.get('hallucination_guard'),
        'segment_count':len(refined.get('segments',[])),
        'file':'transcript_refined.json'
    }
    dump(args.evidence,deep)
    print(json.dumps({'triggered':triggered,'selected_pass':refined.get('selected_pass'),'coverage':(refined.get('quality') or {}).get('coverage')},ensure_ascii=False))

if __name__=='__main__': main()
