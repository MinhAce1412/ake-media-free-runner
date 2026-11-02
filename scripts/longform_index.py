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


def audio_rms(media, outdir, dur):
    wav=outdir/"index_audio.wav"
    subprocess.run(["ffmpeg","-nostdin","-loglevel","error","-y","-i",media,"-vn","-ac","1","-ar","8000","-c:a","pcm_s16le",str(wav)],check=True)
    with wave.open(str(wav),'rb') as wf:
        sr=wf.getframerate(); n=wf.getnframes(); data=np.frombuffer(wf.readframes(n),dtype=np.int16).astype(np.float32)/32768.0
    hop=sr
    rows=[]
    for i in range(0,len(data),hop):
        x=data[i:i+hop]
        if len(x)==0: continue
        rms=float(np.sqrt(np.mean(x*x)))
        db=20*math.log10(max(rms,1e-8))
        rows.append({"time":round(i/sr,2),"rms_db":round(db,2)})
    try: wav.unlink()
    except Exception: pass
    vals=[r["rms_db"] for r in rows]
    p90=float(np.percentile(vals,90)) if vals else -120.0
    return rows,p90


def cluster_windows(anchors,dur,max_windows=20):
    if not anchors: return []
    anchors=sorted(anchors,key=lambda x:x["time"])
    clusters=[]; cur=[]
    for a in anchors:
        if not cur or a["time"]-cur[-1]["time"]<=35:
            cur.append(a)
        else:
            clusters.append(cur); cur=[a]
    if cur: clusters.append(cur)
    out=[]
    for c in clusters:
        times=[x["time"] for x in c]; center=float(np.median(times))
        score=sum(x.get("weight",1.0) for x in c)
        kinds=sorted(set(x["kind"] for x in c))
        st=max(0.0,center-45.0); en=min(dur,center+75.0)
        out.append({"start":round(st,2),"end":round(en,2),"center":round(center,2),"signal_score":round(score,2),"signal_types":kinds,"anchor_count":len(c)})
    out.sort(key=lambda x:(-x["signal_score"],x["start"]))
    return out[:max_windows]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("media"); ap.add_argument("--content-id",required=True); ap.add_argument("--source-url",required=True)
    ap.add_argument("--out",required=True); ap.add_argument("--max-windows",type=int,default=20)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    dur=duration(a.media)
    step=max(10.0,dur/240.0)
    times=np.arange(0,dur+1e-6,step).tolist()
    cap=cv2.VideoCapture(a.media)
    samples=[]; diffs=[]; prev=None
    ocr_slots=set(np.linspace(0,max(0,len(times)-1),min(80,len(times))).astype(int).tolist()) if times else set()
    ocr=[]
    for i,t in enumerate(times):
        f=frame_at(cap,t)
        if f is None: continue
        small=resize(f,640); gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if prev is not None:
            if prev.shape!=gray.shape: gray=cv2.resize(gray,(prev.shape[1],prev.shape[0]))
            diffs.append({"time":round(t,2),"diff":round(float(np.mean(cv2.absdiff(prev,gray))),3)})
        prev=gray
        samples.append((t,f))
        if i in ocr_slots:
            try:
                img=resize(f,960)
                txt=pytesseract.image_to_string(img,lang="vie+eng",config="--psm 6").strip().replace("\n"," ")
                if len(txt)>=8: ocr.append({"time":round(t,2),"text":txt[:500]})
            except Exception: pass
    cap.release()
    vals=[x["diff"] for x in diffs]; vp90=float(np.percentile(vals,90)) if vals else 0.0
    visual=[x for x in diffs if vp90 and x["diff"]>=vp90]
    audio,ap90=audio_rms(a.media,out,dur)
    audio_peaks=[x for x in audio if x["rms_db"]>=ap90]
    anchors=[{"time":x["time"],"kind":"visual_change","weight":1.2} for x in visual]
    anchors += [{"time":x["time"],"kind":"audio_energy","weight":1.0} for x in audio_peaks]
    # OCR is evidence/context, not enough to make a content claim. Add modest weight only when text is substantial.
    anchors += [{"time":x["time"],"kind":"ocr_context","weight":0.5} for x in ocr if len(x["text"])>=30]
    windows=cluster_windows(anchors,dur,a.max_windows)
    # Whole-timeline overview contact sheet.
    overview=[]
    if samples:
        for idx in np.linspace(0,len(samples)-1,min(24,len(samples))).astype(int).tolist(): overview.append((samples[idx][0],samples[idx][1]))
    contact_sheet(overview,out/"longform_contact_sheet.jpg")
    evidence={
      "content_id":a.content_id,"source_url":a.source_url,"duration":round(dur,3),
      "index_state":"LONGFORM_INDEX_EVIDENCE_READY","sample_interval_sec":round(step,2),"visual_sample_count":len(samples),
      "visual_diff_p90":round(vp90,3),"audio_rms_p90_db":round(ap90,2),
      "visual_change_signals":visual[:200],"audio_energy_signals":audio_peaks[:300],"ocr_context":ocr[:200],
      "candidate_windows":windows,
      "rule":"This index proposes candidate windows only. It does NOT establish content type, story or editor decisions. Selected windows require multimodal DEEP review before training or clip recommendation."
    }
    (out/"longform_index.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"candidate_windows.json").write_text(json.dumps(windows,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"content_id":a.content_id,"duration":dur,"samples":len(samples),"candidate_windows":len(windows)},ensure_ascii=False))

if __name__=="__main__": main()
