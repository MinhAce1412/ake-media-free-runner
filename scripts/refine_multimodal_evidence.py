#!/usr/bin/env python3
import argparse, json, math, os, subprocess, tempfile
from pathlib import Path
from collections import defaultdict

import numpy as np
import librosa


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def extract_audio(media, wav):
    subprocess.run([
        'ffmpeg','-nostdin','-loglevel','error','-y','-i',media,
        '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',wav
    ], check=True)


def transcript_pass(wav, model, language, vad):
    kwargs = dict(
        beam_size=5,
        word_timestamps=True,
        vad_filter=vad,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    if language:
        kwargs['language'] = language
    seg_iter, info = model.transcribe(wav, **kwargs)
    rows=[]
    for s in seg_iter:
        avg_lp=float(getattr(s,'avg_logprob',-99.0) or -99.0)
        no_sp=float(getattr(s,'no_speech_prob',0.0) or 0.0)
        text=(s.text or '').strip()
        if not text:
            continue
        words=[]
        for w in getattr(s,'words',[]) or []:
            words.append({'start':round(float(w.start),3),'end':round(float(w.end),3),'word':w.word})
        rows.append({
            'start':round(float(s.start),3),'end':round(float(s.end),3),'text':text,
            'avg_logprob':round(avg_lp,3),'no_speech_prob':round(no_sp,3),'words':words
        })
    return {
        'vad_filter':vad,
        'language':getattr(info,'language',language),
        'language_probability':round(float(getattr(info,'language_probability',0.0) or 0.0),3),
        'segments':rows
    }


def transcript_score(pass_data, duration):
    segs=[]
    suspicious=0
    for s in pass_data.get('segments',[]):
        if s.get('no_speech_prob',0) > 0.78 or s.get('avg_logprob',-99) < -1.45:
            suspicious += 1
            continue
        segs.append(s)
    chars=sum(len(''.join(s['text'].split())) for s in segs)
    speech=sum(max(0.0,s['end']-s['start']) for s in segs)
    coverage=min(1.0, speech/max(duration,1e-9))
    words=' '.join(s['text'].lower() for s in segs).split()
    uniq=len(set(words))/max(len(words),1)
    score = chars + 55.0*coverage + 12.0*uniq - 8.0*suspicious
    return score, segs, {'chars':chars,'speech_seconds':round(speech,3),'coverage':round(coverage,3),'unique_word_ratio':round(uniq,3),'filtered_suspicious_segments':suspicious}


def refine_asr(wav, duration, out_dir):
    try:
        from faster_whisper import WhisperModel
        model_name=os.environ.get('AKE_WHISPER_MODEL','small')
        model=WhisperModel(model_name,device='cpu',compute_type='int8')
        p1=transcript_pass(wav,model,None,True)
        lang=p1.get('language') if p1.get('language_probability',0)>=0.70 else None
        p2=transcript_pass(wav,model,lang,False)
        candidates=[]
        for p in (p1,p2):
            score,segs,meta=transcript_score(p,duration)
            q=dict(p); q['score']=round(score,2); q['quality']=meta; q['usable_segments']=segs
            candidates.append(q)
        best=max(candidates,key=lambda x:x['score'])
        result={
            'status':'ok','model':model_name,'selected_pass':'vad_on' if best['vad_filter'] else 'vad_off',
            'language':best.get('language'),'language_probability':best.get('language_probability'),
            'quality':best['quality'],'segments':best['usable_segments'],
            'alternatives':[{'vad_filter':x['vad_filter'],'score':x['score'],'quality':x['quality'],'segment_count':len(x['usable_segments'])} for x in candidates],
            'warning':'ASR remains a machine transcript. Names, card values and slang must be checked against audio/visual evidence before quoting.'
        }
        dump(out_dir/'transcript_refined.json',result)
        with open(out_dir/'transcript_refined.txt','w',encoding='utf-8') as f:
            for s in result['segments']:
                f.write(f"[{s['start']:07.3f}-{s['end']:07.3f}] {s['text']}\n")
        return result
    except Exception as e:
        result={'status':'failed','error':str(e),'segments':[]}
        dump(out_dir/'transcript_refined.json',result)
        return result


def merge_label_events(items, hop=0.48, max_gap=0.55):
    by=defaultdict(list)
    for it in items: by[it['label']].append(it)
    merged=[]
    for label, rows in by.items():
        rows=sorted(rows,key=lambda x:x['time'])
        cur=None
        for r in rows:
            st=max(0.0,r['time']-hop/2); en=r['time']+hop/2
            if cur is None or st-cur['end']>max_gap:
                if cur: merged.append(cur)
                cur={'label':label,'start':st,'end':en,'scores':[r['score']]}
            else:
                cur['end']=max(cur['end'],en); cur['scores'].append(r['score'])
        if cur: merged.append(cur)
    out=[]
    for r in merged:
        out.append({'label':r['label'],'start':round(r['start'],3),'end':round(r['end'],3),'max_score':round(max(r['scores']),3),'mean_score':round(float(np.mean(r['scores'])),3),'evidence':'YAMNET_MODEL_CANDIDATE'})
    return sorted(out,key=lambda x:(x['start'],-x['max_score']))


def yamnet_refine(wav,out_dir):
    try:
        import tensorflow as tf
        import tensorflow_hub as hub
        model=hub.load('https://tfhub.dev/google/yamnet/1')
        wave,_=librosa.load(wav,sr=16000,mono=True)
        scores,_,_=model(tf.convert_to_tensor(wave,dtype=tf.float32))
        scores=scores.numpy()
        class_map_path=model.class_map_path().numpy().decode('utf-8')
        import csv
        with open(class_map_path,encoding='utf-8') as f:
            names=[r['display_name'] for r in csv.DictReader(f)]
        hop=0.48
        music_idxs=[i for i,n in enumerate(names) if n=='Music']
        speech_idxs=[i for i,n in enumerate(names) if n=='Speech']
        music=np.max(scores[:,music_idxs],axis=1) if music_idxs else np.zeros(scores.shape[0])
        speech=np.max(scores[:,speech_idxs],axis=1) if speech_idxs else np.zeros(scores.shape[0])
        exclude_terms=('music','speech','singing','song','musical instrument','vocal','choir')
        points=[]
        for fi,row in enumerate(scores):
            top=np.argsort(row)[::-1][:18]
            t=fi*hop+0.48
            for idx in top:
                label=names[int(idx)]; score=float(row[int(idx)])
                low=label.lower()
                if score<0.10 or any(x in low for x in exclude_terms):
                    continue
                points.append({'time':round(t,3),'label':label,'score':score})
        events=merge_label_events(points,hop=hop)
        events=[e for e in events if e['max_score']>=0.12][:120]
        result={
            'status':'ok','model':'YAMNet AudioSet 521','frame_hop_seconds':hop,
            'music_presence':{
                'mean_score':round(float(np.mean(music)),3),'coverage_score_ge_0_5':round(float(np.mean(music>=0.5)),3),
                'interpretation':'MUSIC_LIKELY_PRESENT' if float(np.mean(music>=0.5))>=0.35 else 'MUSIC_NOT_STRONGLY_ESTABLISHED'
            },
            'speech_presence':{'mean_score':round(float(np.mean(speech)),3),'coverage_score_ge_0_3':round(float(np.mean(speech>=0.3)),3)},
            'sfx_candidates':events,
            'warning':'SFX labels are AudioSet model candidates, not ground truth. Exact meme/SFX names require listening or independent verification.'
        }
        dump(out_dir/'audio_sfx_refined.json',result)
        return result
    except Exception as e:
        result={'status':'failed','error':str(e),'sfx_candidates':[]}
        dump(out_dir/'audio_sfx_refined.json',result)
        return result


def energy_changes(wav,out_dir):
    y,sr=librosa.load(wav,sr=16000,mono=True)
    hop=int(sr*0.25); frame=int(sr*0.5)
    rms=librosa.feature.rms(y=y,frame_length=frame,hop_length=hop,center=True)[0]
    db=librosa.amplitude_to_db(np.maximum(rms,1e-8),ref=1.0)
    times=librosa.frames_to_time(np.arange(len(db)),sr=sr,hop_length=hop)
    changes=[]
    for i in range(1,len(db)):
        delta=float(db[i]-db[i-1])
        if abs(delta)>=5.0:
            changes.append({'time':round(float(times[i]),3),'delta_db':round(delta,2),'type':'ENERGY_RISE' if delta>0 else 'ENERGY_DROP','evidence':'MEASURED_MIX_ENERGY_CHANGE'})
    result={'window_seconds':0.5,'hop_seconds':0.25,'events':changes[:100],'warning':'These are mixed-audio energy changes, not automatically music drops or SFX.'}
    dump(out_dir/'audio_energy_changes.json',result)
    return result


def overlaps(a,b,c,d): return max(a,c) < min(b,d)


def build_timeline(deep, transcript, sfx, energy, out_dir):
    scenes=(deep.get('scene_detection') or {}).get('scenes') or [deep.get('range',{})]
    ocr=(deep.get('ocr') or {}).get('ocr_events') or []
    visual=(deep.get('visual_machine_events') or {})
    zooms=visual.get('zoom_candidates') or []
    freezes=visual.get('freeze_candidates') or []
    spikes=visual.get('visual_change_spikes') or []
    segs=[]
    for i,sc in enumerate(scenes,1):
        st=float(sc['start']); en=float(sc['end'])
        tr=[x for x in transcript.get('segments',[]) if overlaps(st,en,float(x['start']),float(x['end']))]
        sx=[x for x in sfx.get('sfx_candidates',[]) if overlaps(st,en,float(x['start']),float(x['end']))]
        enrg=[x for x in energy.get('events',[]) if st<=float(x['time'])<en]
        oc=[x for x in ocr if st<=float(x.get('time',-1))<en]
        zm=[x for x in zooms if st<=float(x.get('time',-1))<en]
        fr=[x for x in freezes if overlaps(st,en,float(x['start']),float(x['end']))]
        sp=[x for x in spikes if st<=float(x.get('time',-1))<en]
        segs.append({
            'segment':i,'start':round(st,3),'end':round(en,3),'duration':round(en-st,3),
            'transcript':tr,'ocr_candidates':oc[:6],'sfx_model_candidates':sx[:8],'energy_changes':enrg[:8],
            'visual_candidates':{'zoom':zm[:6],'freeze':fr[:6],'change_spikes':sp[:6]},
            'editor_decision_fields':{
                'observed_edit':'AKE_TO_FILL_AFTER_VISUAL_AUDIO_REVIEW',
                'purpose':'AKE_TO_JUSTIFY','why_here':'AKE_TO_JUSTIFY','confidence':'UNSET','minh_keep_adapt_skip':'UNSET'
            }
        })
    result={
        'status':'EVIDENCE_TIMELINE_READY','segments':segs,
        'rule':'Machine signals are evidence inputs. Ake must inspect the visual proof and corroborate audio before converting them into editor decisions or reasons.'
    }
    dump(out_dir/'editor_timeline_evidence.json',result)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('media'); ap.add_argument('--out',required=True); ap.add_argument('--evidence',required=True)
    args=ap.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    deep=load(args.evidence,{})
    duration=float((deep.get('range') or {}).get('duration') or 0)
    with tempfile.TemporaryDirectory() as td:
        wav=str(Path(td)/'audio.wav'); extract_audio(args.media,wav)
        transcript=refine_asr(wav,duration,out)
        sfx=yamnet_refine(wav,out)
        energy=energy_changes(wav,out)
    timeline=build_timeline(deep,transcript,sfx,energy,out)

    # Reconcile stale scene status from the first-pass visual_events file with the corrected scene detector.
    vp=out/'visual_events.json'
    visual_file=load(vp,{})
    if deep.get('scene_detection'):
        visual_file['scenes']=deep['scene_detection']
        dump(vp,visual_file)

    deep['transcript_refined']={'status':transcript.get('status'),'quality':transcript.get('quality'),'segment_count':len(transcript.get('segments',[])),'file':'transcript_refined.json'}
    deep['audio_sfx_refined']={'status':sfx.get('status'),'music_presence':sfx.get('music_presence'),'sfx_candidate_count':len(sfx.get('sfx_candidates',[])),'file':'audio_sfx_refined.json'}
    deep['editor_timeline']={'status':timeline.get('status'),'segment_count':len(timeline.get('segments',[])),'file':'editor_timeline_evidence.json'}
    deep['evidence_level']='MULTIMODAL_MACHINE_EVIDENCE_READY_REQUIRES_AKE_SYNTHESIS'
    deep['full_editor_review_gate']={
        'ready_for_Ake_synthesis': True,
        'may_claim_full_editor_review_only_after':[
            'Ake opens hook/timeline contact sheets and relevant boundary proof strips',
            'Ake checks transcript wording against audio confidence and visual context',
            'Ake treats YAMNet SFX labels as candidates unless independently corroborated',
            'Ake explains every hook/edit/audio decision with an explicit evidence-backed WHY HERE',
            'Ake labels unknown music/SFX names UNKNOWN rather than guessing'
        ]
    }
    dump(args.evidence,deep)
    print(json.dumps({'status':'ok','transcript_segments':len(transcript.get('segments',[])),'sfx_candidates':len(sfx.get('sfx_candidates',[])),'timeline_segments':len(timeline.get('segments',[]))},ensure_ascii=False))

if __name__=='__main__': main()
