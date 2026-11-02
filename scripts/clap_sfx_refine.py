#!/usr/bin/env python3
import argparse, json, math, os, subprocess, tempfile
from pathlib import Path


def load(p, default=None):
    try: return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception: return default if default is not None else {}

def dump(p,d): Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')

def ffprobe_duration(media):
    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',media],capture_output=True,text=True,check=True)
    return float(r.stdout.strip())

def uniq_times(vals, gap=.55, cap=18):
    out=[]
    for t in sorted(max(0.0,float(x)) for x in vals):
        if not out or t-out[-1]>=gap: out.append(t)
    return out[:cap]

def extract_window(media, center, dur, out):
    start=max(0.0,center-dur/2)
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-ss',f'{start:.3f}','-i',media,'-t',f'{dur:.3f}','-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',out],check=True)
    return start

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('media'); ap.add_argument('--evidence',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    deep=load(args.evidence,{})
    energy=load(out/'audio_energy_changes.json',{})
    duration=ffprobe_duration(args.media)
    times=[]
    times += [e.get('time',0) for e in energy.get('events',[]) or []]
    for s in (deep.get('scene_detection') or {}).get('scenes',[])[:-1]: times.append(s.get('end',0))
    times=uniq_times(times)
    labels=[
      'a whoosh or swoosh transition sound',
      'a cinematic impact or bass hit sound effect',
      'a short pop sound effect',
      'a click or interface button sound',
      'a rising riser or sweep sound effect',
      'a notification or chime sound',
      'crowd cheering',
      'human laughter',
      'applause or clapping',
      'an explosion or game impact sound',
      'football video game sound effects',
      'speech with background music',
      'background music without a distinct added sound effect',
      'mixed game audio without a distinct added editing sound effect'
    ]
    try:
        from transformers import pipeline
        clf=pipeline('zero-shot-audio-classification',model='laion/clap-htsat-unfused',device=-1)
        results=[]
        with tempfile.TemporaryDirectory() as td:
            for i,t in enumerate(times):
                wav=str(Path(td)/f'w{i:02d}.wav'); st=extract_window(args.media,t,1.8,wav)
                pred=clf(wav,candidate_labels=labels)
                pred=sorted(pred,key=lambda x:x['score'],reverse=True)
                top=pred[0] if pred else {'label':'UNKNOWN','score':0}; second=pred[1] if len(pred)>1 else {'score':0}
                score=float(top['score']); margin=score-float(second['score'])
                distinct=not any(x in top['label'] for x in ['background music','mixed game audio','speech with'])
                accepted=bool(distinct and score>=0.28 and margin>=0.035)
                results.append({
                  'center_time':round(t,3),'window_start':round(st,3),'window_duration':1.8,
                  'candidate':top['label'] if accepted else 'UNKNOWN',
                  'accepted_as_candidate':accepted,
                  'top_score':round(score,4),'margin_vs_second':round(margin,4),
                  'top5':[{'label':p['label'],'score':round(float(p['score']),4)} for p in pred[:5]],
                  'evidence':'CLAP_ZERO_SHOT_CANDIDATE_ONLY'
                })
        d={
          'status':'ok','model':'laion/clap-htsat-unfused','tested_windows':len(results),'results':results,
          'rule':'CLAP output is a semantic candidate, not proof of an exact SFX. Ake may only elevate a label when it also matches visual timing/energy evidence; exact meme/sample identity stays UNKNOWN unless separately identified.'
        }
    except Exception as e:
        d={'status':'failed','error':str(e),'results':[],'rule':'CLAP optional failure must not block core DEEP analysis.'}
    dump(out/'clap_sfx_candidates.json',d)
    print(json.dumps({'status':d.get('status'),'tested_windows':len(d.get('results',[])),'accepted':sum(1 for x in d.get('results',[]) if x.get('accepted_as_candidate'))},ensure_ascii=False))
if __name__=='__main__': main()
