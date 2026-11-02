#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import traceback
from pathlib import Path

import cv2
import librosa
import numpy as np
import pytesseract
import soundfile as sf
from pytesseract import Output


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def ffprobe_duration(path: str) -> float:
    r = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ])
    return float(r.stdout.strip())


def extract_audio(media: str, wav_out: str):
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", media,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_out,
    ], check=True)


def frame_at(cap, t: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def resize_for_analysis(frame, max_width=960):
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    scale = max_width / float(w)
    return cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)


def make_contact_sheet(items, out_path: str, cols=4, tile_w=260):
    if not items:
        return False
    rendered = []
    for t, img in items:
        h, w = img.shape[:2]
        scale = tile_w / float(w)
        tile = cv2.resize(img, (tile_w, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, 0), (tile_w, 30), (0, 0, 0), -1)
        cv2.putText(tile, f"{t:06.2f}s", (7, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255,255,255), 1, cv2.LINE_AA)
        rendered.append(tile)
    max_h = max(x.shape[0] for x in rendered)
    rows = math.ceil(len(rendered) / cols)
    canvas = np.zeros((rows * max_h, cols * tile_w, 3), dtype=np.uint8)
    for i, tile in enumerate(rendered):
        r, c = divmod(i, cols)
        canvas[r*max_h:r*max_h+tile.shape[0], c*tile_w:(c+1)*tile_w] = tile
    return bool(cv2.imwrite(out_path, canvas))


def detect_scenes(media: str, start: float, end: float):
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import AdaptiveDetector
        video = open_video(media)
        manager = SceneManager()
        manager.add_detector(AdaptiveDetector())
        manager.detect_scenes(video, start_time=start, end_time=end)
        raw = manager.get_scene_list(start_in_scene=True)
        scenes = []
        for a, b in raw:
            s, e = a.get_seconds(), b.get_seconds()
            s, e = max(start, s), min(end, e)
            if e > s:
                scenes.append({"start": round(s,3), "end": round(e,3), "duration": round(e-s,3)})
        if not scenes:
            scenes = [{"start": round(start,3), "end": round(end,3), "duration": round(end-start,3)}]
        return {"status":"ok", "method":"PySceneDetect AdaptiveDetector", "scenes":scenes}
    except Exception as e:
        return {"status":"failed", "error":str(e), "scenes":[{"start":start,"end":end,"duration":end-start}]}


def dense_visual_analysis(media: str, start: float, end: float, out_dir: Path):
    cap = cv2.VideoCapture(media)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # 4 fps for continuous motion evidence, capped to keep CPU predictable.
    step = 0.25
    times = np.arange(start, end + 1e-6, step).tolist()
    if len(times) > 900:
        step = (end-start)/900.0
        times = np.arange(start, end + 1e-6, step).tolist()

    orb = cv2.ORB_create(nfeatures=600)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    prev_gray = None
    prev_kp = prev_des = None
    diffs, transforms = [], []

    freeze_runs = []
    freeze_start = None
    zoom_candidates = []

    for idx, t in enumerate(times):
        frame = frame_at(cap, t)
        if frame is None:
            continue
        small = resize_for_analysis(frame, 640)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        kp, des = orb.detectAndCompute(gray, None)
        if prev_gray is not None:
            if prev_gray.shape != gray.shape:
                gray = cv2.resize(gray, (prev_gray.shape[1], prev_gray.shape[0]))
            diff = float(np.mean(cv2.absdiff(prev_gray, gray)))
            diffs.append({"time":round(t,3), "mean_absdiff":round(diff,3)})
            if diff < 1.25:
                if freeze_start is None:
                    freeze_start = max(start, t-step)
            else:
                if freeze_start is not None and (t-freeze_start) >= 0.5:
                    freeze_runs.append({"start":round(freeze_start,3), "end":round(t,3), "duration":round(t-freeze_start,3), "confidence":"HEURISTIC"})
                freeze_start = None

            if prev_des is not None and des is not None and len(prev_des) >= 12 and len(des) >= 12:
                try:
                    matches = sorted(bf.match(prev_des, des), key=lambda m: m.distance)[:120]
                    if len(matches) >= 12:
                        src = np.float32([prev_kp[m.queryIdx].pt for m in matches]).reshape(-1,1,2)
                        dst = np.float32([kp[m.trainIdx].pt for m in matches]).reshape(-1,1,2)
                        M, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
                        if M is not None:
                            scale = float(math.sqrt(M[0,0]**2 + M[0,1]**2))
                            tx, ty = float(M[0,2]), float(M[1,2])
                            inlier_ratio = float(np.mean(inliers)) if inliers is not None else 0.0
                            transforms.append({"time":round(t,3),"scale":round(scale,4),"translation_px":round(math.hypot(tx,ty),2),"inlier_ratio":round(inlier_ratio,3)})
                            if inlier_ratio >= 0.35 and (scale >= 1.035 or scale <= 0.966):
                                zoom_candidates.append({
                                    "time":round(t,3),
                                    "direction":"zoom_in_candidate" if scale>1 else "zoom_out_candidate",
                                    "scale_step":round(scale,4),
                                    "confidence":"HEURISTIC_NOT_VERIFIED_EFFECT"
                                })
                except Exception:
                    pass
        prev_gray, prev_kp, prev_des = gray, kp, des

    if freeze_start is not None and (end-freeze_start) >= 0.5:
        freeze_runs.append({"start":round(freeze_start,3),"end":round(end,3),"duration":round(end-freeze_start,3),"confidence":"HEURISTIC"})
    cap.release()

    vals = [x["mean_absdiff"] for x in diffs]
    p90 = float(np.percentile(vals,90)) if vals else 0.0
    spikes = [x for x in diffs if p90 and x["mean_absdiff"] >= p90]
    return {
        "sampling_fps": round(1.0/step,2),
        "freeze_candidates": freeze_runs,
        "zoom_candidates": zoom_candidates[:100],
        "visual_change_spikes": spikes[:100],
        "transform_samples": transforms[:300],
        "note":"Zoom/freeze/motion outputs are computer-vision candidates. They are not verified editorial effects until Ake inspects surrounding frames/sequence."
    }


def save_key_frames_and_ocr(media: str, start: float, end: float, scenes, out_dir: Path):
    frames_dir = out_dir / "key_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(media)

    times = set()
    # Dense hook sampling.
    hook_end = min(end, start + 5.0)
    t = start
    while t <= hook_end + 1e-6:
        times.add(round(t,3)); t += 0.5
    # Whole selected range, 1 frame/sec. For long ranges, spread to <=180 images.
    whole_step = max(1.0, (end-start)/180.0)
    t = start
    while t <= end + 1e-6:
        times.add(round(t,3)); t += whole_step
    for s in scenes:
        for x in (s["start"], min(s["end"], s["start"]+0.12), max(s["start"], s["end"]-0.12)):
            if start <= x <= end:
                times.add(round(x,3))
    times = sorted(times)

    ocr_events = []
    saved = []
    for i, t in enumerate(times):
        frame = frame_at(cap, t)
        if frame is None:
            continue
        name = f"frame_{i:04d}_{t:07.3f}s.jpg"
        p = frames_dir / name
        cv2.imwrite(str(p), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        saved.append((t, frame, name))

        # OCR on a resized copy. Tesseract is a lightweight first-pass OCR; low confidence remains untrusted.
        img = resize_for_analysis(frame, 1100)
        try:
            d = pytesseract.image_to_data(img, lang="vie+eng", config="--psm 6", output_type=Output.DICT)
            toks=[]
            confs=[]
            for txt, conf in zip(d.get("text",[]), d.get("conf",[])):
                txt=(txt or "").strip()
                try: c=float(conf)
                except Exception: c=-1
                if txt and c >= 45:
                    toks.append(txt); confs.append(c)
            text=" ".join(toks).strip()
            if text:
                ocr_events.append({"time":round(t,3),"text":text[:600],"mean_confidence":round(float(np.mean(confs)),1) if confs else None,"engine":"tesseract vie+eng"})
        except Exception as e:
            ocr_events.append({"time":round(t,3),"status":"ocr_failed","error":str(e)})
    cap.release()

    hook_items=[(t,img) for t,img,_ in saved if t <= hook_end+1e-6]
    if len(hook_items)>12:
        hook_items=hook_items[:12]
    timeline_items=[]
    if saved:
        idxs=np.linspace(0,len(saved)-1,min(20,len(saved))).astype(int).tolist()
        timeline_items=[(saved[i][0],saved[i][1]) for i in idxs]
    make_contact_sheet(hook_items, str(out_dir/"hook_contact_sheet.jpg"), cols=4, tile_w=270)
    make_contact_sheet(timeline_items, str(out_dir/"timeline_contact_sheet.jpg"), cols=4, tile_w=250)

    return {"saved_frame_count":len(saved),"frame_times":[round(x[0],3) for x in saved],"ocr_events":ocr_events}


def transcribe(wav_path: str, out_dir: Path):
    result={"status":"not_run","segments":[],"language":None,"language_probability":None}
    try:
        from faster_whisper import WhisperModel
        model_name=os.environ.get("AKE_WHISPER_MODEL","small")
        model=WhisperModel(model_name, device="cpu", compute_type="int8")
        segs, info=model.transcribe(wav_path, beam_size=3, vad_filter=True, word_timestamps=True)
        data=[]
        for s in segs:
            words=[]
            if getattr(s,"words",None):
                for w in s.words:
                    words.append({"start":round(float(w.start),3),"end":round(float(w.end),3),"word":w.word})
            data.append({"start":round(float(s.start),3),"end":round(float(s.end),3),"text":s.text.strip(),"words":words})
        result={"status":"ok","model":model_name,"language":getattr(info,"language",None),"language_probability":round(float(getattr(info,"language_probability",0.0)),3),"segments":data}
        with open(out_dir/"transcript.txt","w",encoding="utf-8") as f:
            for s in data:
                f.write(f"[{s['start']:07.3f}-{s['end']:07.3f}] {s['text']}\n")
    except Exception as e:
        result={"status":"failed","error":str(e),"trace":traceback.format_exc(limit=2),"segments":[]}
    return result


def merge_boolean_regions(times, mask, min_dur=0.3):
    if not times:
        return []
    regions=[]; st=None; last=None
    hop=(times[1]-times[0]) if len(times)>1 else 0.1
    for t,m in zip(times,mask):
        if m and st is None: st=t
        if not m and st is not None:
            en=(last if last is not None else t)+hop
            if en-st>=min_dur: regions.append({"start":round(st,3),"end":round(en,3),"duration":round(en-st,3)})
            st=None
        last=t
    if st is not None:
        en=times[-1]+hop
        if en-st>=min_dur: regions.append({"start":round(st,3),"end":round(en,3),"duration":round(en-st,3)})
    return regions


def audio_features(wav_path: str):
    y,sr=librosa.load(wav_path,sr=16000,mono=True)
    if y.size==0:
        return {"status":"empty"}
    hop=2048
    rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=hop)[0]
    rms_db=librosa.amplitude_to_db(np.maximum(rms,1e-8),ref=1.0)
    times=librosa.frames_to_time(np.arange(len(rms)),sr=sr,hop_length=hop).tolist()
    silence=merge_boolean_regions(times,(rms_db<-45).tolist(),0.35)
    onset_env=librosa.onset.onset_strength(y=y,sr=sr)
    onset_frames=librosa.onset.onset_detect(onset_envelope=onset_env,sr=sr,backtrack=False,units="frames")
    onset_times=librosa.frames_to_time(onset_frames,sr=sr).tolist()
    try:
        tempo=librosa.beat.tempo(onset_envelope=onset_env,sr=sr,aggregate=np.median)
        bpm=float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else None
    except Exception:
        bpm=None
    centroid=librosa.feature.spectral_centroid(y=y,sr=sr)[0]
    zcr=librosa.feature.zero_crossing_rate(y)[0]
    peak=float(np.max(np.abs(y)))
    peak_db=20*math.log10(max(peak,1e-9))
    rms_total=float(np.sqrt(np.mean(y*y)))
    rms_total_db=20*math.log10(max(rms_total,1e-9))
    return {
        "status":"ok","sample_rate":sr,"duration":round(len(y)/sr,3),
        "estimated_tempo_bpm":round(bpm,1) if bpm and np.isfinite(bpm) else None,
        "peak_dbfs":round(peak_db,2),"rms_dbfs":round(rms_total_db,2),
        "mean_spectral_centroid_hz":round(float(np.mean(centroid)),1),
        "mean_zero_crossing_rate":round(float(np.mean(zcr)),4),
        "onset_times":[round(float(x),3) for x in onset_times[:250]],
        "silence_regions":silence[:100],
        "note":"Tempo/onsets describe the mixed soundtrack, not necessarily the background-music track alone."
    }


def yamnet_events(wav_path: str):
    try:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL","2")
        import tensorflow as tf
        import tensorflow_hub as hub
        y,sr=librosa.load(wav_path,sr=16000,mono=True)
        model=hub.load("https://tfhub.dev/google/yamnet/1")
        scores, embeddings, spectrogram=model(tf.convert_to_tensor(y,dtype=tf.float32))
        scores=scores.numpy()
        class_map_path=model.class_map_path().numpy().decode("utf-8")
        names=[]
        with open(class_map_path,"r",encoding="utf-8") as f:
            rd=csv.DictReader(f)
            for row in rd: names.append(row["display_name"])
        mean_scores=np.mean(scores,axis=0)
        top=np.argsort(mean_scores)[::-1][:15]
        global_top=[{"label":names[int(i)],"mean_score":round(float(mean_scores[i]),3)} for i in top]

        interesting_terms=("music","speech","laughter","giggle","whoosh","swoosh","swish","bang","explosion","click","tap","clap","applause","crowd","cheer","ding","bell","boom","thump","slam","sound effect","video game","shout","yell","scream")
        raw=[]
        for fi,row in enumerate(scores):
            t=fi*0.48
            for idx in np.argsort(row)[::-1][:8]:
                label=names[int(idx)]; score=float(row[idx])
                if score < 0.18: continue
                if any(term in label.lower() for term in interesting_terms):
                    raw.append({"time":round(t,3),"label":label,"score":round(score,3)})
        # Merge same-label adjacent windows into compact event ranges.
        grouped={}
        for e in raw: grouped.setdefault(e["label"],[]).append(e)
        merged=[]
        for label,events in grouped.items():
            events=sorted(events,key=lambda x:x["time"])
            st=prev=events[0]["time"]; scores_l=[events[0]["score"]]
            for e in events[1:]:
                if e["time"]-prev <= 0.60:
                    prev=e["time"]; scores_l.append(e["score"])
                else:
                    merged.append({"label":label,"start":round(st,3),"end":round(prev+0.96,3),"max_score":round(max(scores_l),3),"mean_score":round(float(np.mean(scores_l)),3)})
                    st=prev=e["time"]; scores_l=[e["score"]]
            merged.append({"label":label,"start":round(st,3),"end":round(prev+0.96,3),"max_score":round(max(scores_l),3),"mean_score":round(float(np.mean(scores_l)),3)})
        merged=sorted(merged,key=lambda x:(x["start"],-x["max_score"]))[:300]
        music_scores=[float(row[i]) for row in scores for i,n in enumerate(names) if n=="Music"] if "Music" in names else []
        return {"status":"ok","model":"YAMNet AudioSet 521 classes","global_top":global_top,"events":merged,"frame_hop_seconds":0.48,"note":"Audio labels are model predictions, not ground-truth. Exact SFX/music names require separate verification."}
    except Exception as e:
        return {"status":"failed","error":str(e),"trace":traceback.format_exc(limit=2),"events":[]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--content-id",required=True)
    ap.add_argument("--source-url",required=True)
    ap.add_argument("--out",default="output/deep")
    ap.add_argument("--start",type=float,default=0.0)
    ap.add_argument("--end",type=float,default=None)
    args=ap.parse_args()

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    total=ffprobe_duration(args.media)
    start=max(0.0,args.start)
    requested_end=total if args.end is None or args.end<=0 else min(total,args.end)
    # One DEEP job covers at most 180 seconds; longer material should be chunked deliberately.
    end=min(requested_end,start+180.0)
    if end<=start: raise SystemExit("Invalid analysis range")

    wav=str(out/"audio_16k_mono.wav")
    extract_audio(args.media,wav)

    scene_data=detect_scenes(args.media,start,end)
    scenes=scene_data.get("scenes",[])
    visual=dense_visual_analysis(args.media,start,end,out)
    ocr=save_key_frames_and_ocr(args.media,start,end,scenes,out)
    transcript=transcribe(wav,out)
    af=audio_features(wav)
    yn=yamnet_events(wav)

    shot_count=len(scenes)
    scene_durations=[s["duration"] for s in scenes if s.get("duration")]
    avg_shot=float(np.mean(scene_durations)) if scene_durations else (end-start)
    cuts=max(0,shot_count-1)
    cut_density=cuts/max((end-start)/10.0,1e-9)

    evidence={
        "analysis_id":f"deep:{args.content_id}:v1",
        "content_id":args.content_id,
        "source_url":args.source_url,
        "analysis_version":"AKE_DEEP_EDITOR_V1",
        "evidence_level":"DEEP_EVIDENCE_READY_NOT_YET_HUMAN_VISUAL_SYNTHESIS",
        "range":{"start":round(start,3),"end":round(end,3),"duration":round(end-start,3),"source_duration":round(total,3),"truncated_for_single_job":requested_end>end+1e-6},
        "scene_detection":scene_data,
        "pacing":{"shot_count":shot_count,"cuts":cuts,"average_shot_length":round(avg_shot,3),"cuts_per_10s":round(cut_density,2)},
        "visual_machine_events":visual,
        "ocr":ocr,
        "transcript":transcript,
        "audio_features":af,
        "audio_event_model":yn,
        "music":{"track_name":"UNKNOWN","rule":"Do not invent an exact song name. Resolve only from verified metadata/public evidence or a legitimate fingerprint/identification source."},
        "review_contract":{
            "verified_machine_evidence":["scene boundaries from PySceneDetect","sampled frames","OCR candidates","ASR transcript if status=ok","audio feature measurements","YAMNet class probabilities if status=ok"],
            "requires_Ake_visual_inspection_before_claiming":["exact first-frame composition","actual zoom/punch-in/freeze effect","meme insert identity","caption styling","reaction framing","editorial purpose"],
            "requires_audio_evidence_before_claiming":["spoken hook wording","SFX type","music presence/role","silence/drop","game-vs-BGM balance"],
            "never_infer_from_one_video":["platform algorithm rule","causal retention effect","trend demand"]
        }
    }

    with open(out/"deep_evidence.json","w",encoding="utf-8") as f:
        json.dump(evidence,f,ensure_ascii=False,indent=2)
    with open(out/"transcript.json","w",encoding="utf-8") as f:
        json.dump(transcript,f,ensure_ascii=False,indent=2)
    with open(out/"audio_events.json","w",encoding="utf-8") as f:
        json.dump({"features":af,"yamnet":yn},f,ensure_ascii=False,indent=2)
    with open(out/"visual_events.json","w",encoding="utf-8") as f:
        json.dump({"scenes":scene_data,"visual":visual,"ocr":ocr},f,ensure_ascii=False,indent=2)

    with open(out/"scenes.csv","w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["start","end","duration"]); w.writeheader(); w.writerows(scenes)

    # Source audio is only an intermediate. Keep measurements/transcript, not third-party audio bytes.
    try: os.remove(wav)
    except OSError: pass

    print(json.dumps({"status":"ok","analysis_id":evidence["analysis_id"],"range":evidence["range"],"shot_count":shot_count,"transcript_status":transcript.get("status"),"yamnet_status":yn.get("status"),"saved_frames":ocr.get("saved_frame_count")},ensure_ascii=False))


if __name__=="__main__":
    main()
