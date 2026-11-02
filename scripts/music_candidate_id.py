#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path


def choose_window(evidence):
    duration=float(evidence.get('range',{}).get('duration') or 0)
    events=evidence.get('audio_event_model',{}).get('events',[]) or []
    music=[]
    for e in events:
        if 'music' in str(e.get('label','')).lower():
            music.append(e)
    if music:
        best=max(music,key=lambda e: float(e.get('max_score') or e.get('mean_score') or 0))
        center=(float(best.get('start',0))+float(best.get('end',0)))/2
    else:
        center=max(0,duration/2)
    length=min(12.0,max(6.0,duration)) if duration else 10.0
    start=max(0.0,center-length/2)
    if duration and start+length>duration: start=max(0.0,duration-length)
    return round(start,3),round(length,3)

async def recognize(path):
    from shazamio import Shazam
    shazam=Shazam()
    return await shazam.recognize(path)


def simplify(raw):
    track=(raw or {}).get('track') or {}
    if not track:
        return {'status':'NO_MATCH','track_name':'UNKNOWN','artist':None,'candidate_confidence':'NONE','raw_track_key':None}
    return {
        'status':'CANDIDATE_EXTERNAL_MATCH',
        'track_name':track.get('title') or 'UNKNOWN',
        'artist':track.get('subtitle'),
        'candidate_confidence':'UNVERIFIED_EXTERNAL_CANDIDATE',
        'raw_track_key':track.get('key'),
        'shazam_url':track.get('url'),
        'rule':'Do not promote this candidate to VERIFIED_TRACK until it is cross-checked against public metadata/search or another independent source. Reverse-engineered music recognition may be wrong or unavailable.'
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('media'); ap.add_argument('--evidence',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    evidence=json.load(open(args.evidence,encoding='utf-8'))
    start,length=choose_window(evidence)
    snippet=out/'music_probe.wav'
    result={'status':'UNKNOWN','track_name':'UNKNOWN','window':{'start':start,'duration':length},'source':'ShazamIO best-effort free candidate only'}
    try:
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-ss',str(start),'-t',str(length),'-i',args.media,'-vn','-ac','1','-ar','44100',str(snippet)],check=True)
        raw=asyncio.run(recognize(str(snippet)))
        result.update(simplify(raw)); result['window']={'start':start,'duration':length}; result['source']='ShazamIO 0.8.1 candidate'
    except Exception as e:
        result={'status':'FAILED_OR_NO_SERVICE','track_name':'UNKNOWN','window':{'start':start,'duration':length},'error':str(e),'source':'ShazamIO best-effort free candidate only','rule':'Failure does not fail DEEP review and exact track remains UNKNOWN.'}
    finally:
        try: os.remove(snippet)
        except OSError: pass
    with open(out/'music_identification.json','w',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
