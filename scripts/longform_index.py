#!/usr/bin/env python3
import argparse, json, math, subprocess, wave
from pathlib import Path

import cv2
import numpy as np
import pytesseract


def cmd(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def duration(path):
    return float(cmd(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path]).stdout.strip())


def frame_at(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0,t)*1000.0)
    ok, f=cap.read()
    return f if ok else None


def resize(frame, width=640):
    h,w=frame.shape[:2]
    if w<=width: return frame
    s=width/float(w)
    return cv2.resize(frame,(width,max(1,int(h*s))),interpolation=cv2.INTER_AREA)


def contact_sheet(items, out, cols=4, tile_w=280):
    if not items: return False
    tiles=[]
    for t,img in items:
        h,w=img.shape[:2]; s=tile_w/float(w)
        tile=cv2.resize(img,(tile_w,max(1,int(h*s))),interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile,(0,0),(tile_w,30),(0,0,0),-1)
        cv2.putText(tile,f"{t/60:.1f}m",(8,21),cv2.FONT_HERSHEY_SIMPLEX,.58,(255,255,255),1,cv2.LINE_AA)
        tiles.append(tile)
    mh=max(x.shape[0] for x in tiles); rows=math.ceil(len(tiles)/cols)
    canvas=np.zeros((rows*mh,cols*tile_w,3),dtype=np.uint8)
    for i,tile in enumerate(tiles):
        r,c=divmod(i,cols); canvas[r*mh:r*mh+tile.shape[0],c*tile_w:(c+1)*tile_w]=tile
    return bool(cv2.imwrite(str(out),canvas))


def audio_rms(media, outdir):
    wav=outdir/"index_audio.wav"
    subprocess.run(["ffmpeg","-nostdin","-loglevel","error","-y","-i",media,"-vn","-ac","1","-ar","8000","-c:a","pcm_s16le",str(wav)],check=True)
    with wave.open(str(wav),'rb') as wf:
        sr=wf.getframerate(); n=wf.getnframes(); data=np.frombuffer(wf.readframes(n),dtype=np.int16).astype(np.float32)/32768.0
    rows=[]; hop=sr
    for i in range(0,len(data),hop):
        x=data[i:i+hop]
        if len(x)==0: continue
        rms=float(np.sqrt(np.mean(x*x))); db=20*math.log10(max(rms,1e-8))
        rows.append({"time":round(i/sr,2),"rms_db":round(db,2)})
    try: wav.unlink()
    except Exception: pass
    vals=[r["rms_db"] for r in rows]
    return rows,(float(np.percentile(vals,90)) if vals else -120.0)


def nms_peaks(rows, value_key, threshold, min_gap=18.0, max_keep=100):
    """Keep strong, time-separated peaks so dense 1s audio frames cannot chain the whole VOD."""
    cand=[r for r in rows if float(r[value_key])>=threshold]
    cand.sort(key=lambda r:float(r[value_key]), reverse=True)
    kept=[]
    for r in cand:
        t=float(r["time"])
        if all(abs(t-float(k["time"]))>=min_gap for k in kept):
            kept.append(r)
            if len(kept)>=max_keep: break
    return sorted(kept,key=lambda r:float(r["time"]))


def bucket_windows(anchors,dur,max_windows=20,bucket_sec=120.0,context=15.0):
    """Score fixed time buckets instead of chain-clustering adjacent peaks."""
    if not anchors: return []
    buckets={}
    for a in anchors:
        b=int(float(a["time"])//bucket_sec)
        buckets.setdefault(b,[]).append(a)
    out=[]
    for b,items in buckets.items():
        raw_start=b*bucket_sec; raw_end=min(dur,(b+1)*bucket_sec)
        start=max(0.0,raw_start-context); end=min(dur,raw_end+context)
        score=sum(float(x.get("weight",1.0)) for x in items)
        kinds=sorted(set(x["kind"] for x in items))
        center=float(np.average([x["time"] for x in items],weights=[x.get("weight",1.0) for x in items]))
        out.append({"start":round(start,2),"end":round(end,2),"center":round(center,2),"signal_score":round(score,2),"signal_types":kinds,"anchor_count":len(items),"bucket_start":round(raw_start,2),"bucket_end":round(raw_end,2)})
    out.sort(key=lambda x:(-x["signal_score"],x["start"]))
    return out[:max_windows]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("media"); ap.add_argument("--content-id",required=True); ap.add_argument("--source-url",required=True)
    ap.add_argument("--out",required=True); ap.add_argument("--max-windows",type=int,default=20)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    dur=duration(a.media); step=max(10.0,dur/240.0)
    times=np.arange(0,dur+1e-6,step).tolist(); cap=cv2.VideoCapture(a.media)
    samples=[]; diffs=[]; prev=None
    ocr_slots=set(np.linspace(0,max(0,len(times)-1),min(80,len(times))).astype(int).tolist()) if times else set(); ocr=[]
    for i,t in enumerate(times):
        f=frame_at(cap,t)
        if f is None: continue
        small=resize(f,640); gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if prev is not None:
            if prev.shape!=gray.shape: gray=cv2.resize(gray,(prev.shape[1],prev.shape[0]))
            diffs.append({"time":round(t,2),"diff":round(float(np.mean(cv2.absdiff(prev,gray))),3)})
        prev=gray; samples.append((t,f))
        if i in ocr_slots:
            try:
                txt=pytesseract.image_to_string(resize(f,960),lang="vie+eng",config="--psm 6").strip().replace("\n"," ")
                if len(txt)>=8: ocr.append({"time":round(t,2),"text":txt[:500]})
            except Exception: pass
    cap.release()
    vvals=[x["diff"] for x in diffs]; vp90=float(np.percentile(vvals,90)) if vvals else 0.0
    visual_raw=[x for x in diffs if vp90 and x["diff"]>=vp90]
    visual=nms_peaks(diffs,"diff",vp90,min_gap=max(18.0,step*1.5),max_keep=80) if vp90 else []
    audio,ap90=audio_rms(a.media,out)
    audio_raw=[x for x in audio if x["rms_db"]>=ap90]
    audio_peaks=nms_peaks(audio,"rms_db",ap90,min_gap=18.0,max_keep=120)
    anchors=[{"time":x["time"],"kind":"visual_change","weight":1.4} for x in visual]
    anchors += [{"time":x["time"],"kind":"audio_energy","weight":1.0} for x in audio_peaks]
    # OCR is context only; it does not create candidate anchors and cannot bridge the timeline.
    windows=bucket_windows(anchors,dur,a.max_windows,bucket_sec=120.0,context=15.0)
    overview=[]
    if samples:
        for idx in np.linspace(0,len(samples)-1,min(24,len(samples))).astype(int).tolist(): overview.append((samples[idx][0],samples[idx][1]))
    contact_sheet(overview,out/"longform_contact_sheet.jpg")
    evidence={
      "content_id":a.content_id,"source_url":a.source_url,"duration":round(dur,3),
      "index_state":"LONGFORM_INDEX_EVIDENCE_READY","sample_interval_sec":round(step,2),"visual_sample_count":len(samples),
      "visual_diff_p90":round(vp90,3),"audio_rms_p90_db":round(ap90,2),
      "raw_visual_threshold_hits":len(visual_raw),"selected_visual_peaks":visual,
      "raw_audio_threshold_hits":len(audio_raw),"selected_audio_peaks":audio_peaks,
      "ocr_context":ocr[:200],"candidate_windows":windows,
      "rule":"This index proposes candidate windows only. It does NOT establish content type, story or editor decisions. OCR/audio/visual peaks are discovery signals. Selected windows require multimodal DEEP review before training or clip recommendation."
    }
    (out/"longform_index.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"candidate_windows.json").write_text(json.dumps(windows,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"content_id":a.content_id,"duration":dur,"samples":len(samples),"visual_peaks":len(visual),"audio_peaks":len(audio_peaks),"candidate_windows":len(windows)},ensure_ascii=False))

if __name__=="__main__": main()
