#!/usr/bin/env python3
import argparse, csv, json, math
from pathlib import Path
import cv2
import numpy as np
from scenedetect import detect
from scenedetect.detectors import AdaptiveDetector


def frame_at(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def sheet(items, path, cols=6, tile_w=230):
    if not items: return False
    tiles=[]
    for t,img in items:
        h,w=img.shape[:2]; sc=tile_w/float(w)
        tile=cv2.resize(img,(tile_w,max(1,int(h*sc))),interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile,(0,0),(tile_w,28),(0,0,0),-1)
        cv2.putText(tile,f"{t:07.3f}s",(6,20),cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),1,cv2.LINE_AA)
        tiles.append(tile)
    mh=max(x.shape[0] for x in tiles); rows=math.ceil(len(tiles)/cols)
    canvas=np.zeros((rows*mh,cols*tile_w,3),dtype=np.uint8)
    for i,tile in enumerate(tiles):
        r,c=divmod(i,cols); canvas[r*mh:r*mh+tile.shape[0],c*tile_w:(c+1)*tile_w]=tile
    return bool(cv2.imwrite(str(path),canvas))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('media'); ap.add_argument('--evidence',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    d=json.load(open(args.evidence,encoding='utf-8'))
    start=float(d['range']['start']); end=float(d['range']['end'])

    try:
        raw=detect(args.media, AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=4), start_time=start, end_time=end, start_in_scene=True)
        scenes=[]
        for a,b in raw:
            s=max(start,float(a.get_seconds())); e=min(end,float(b.get_seconds()))
            if e>s: scenes.append({'start':round(s,3),'end':round(e,3),'duration':round(e-s,3)})
        if not scenes: scenes=[{'start':round(start,3),'end':round(end,3),'duration':round(end-start,3)}]
        d['scene_detection']={'status':'ok','method':'PySceneDetect detect() + AdaptiveDetector threshold=3.0 min_scene_len=4','scenes':scenes}
    except Exception as e:
        scenes=d.get('scene_detection',{}).get('scenes') or [{'start':start,'end':end,'duration':end-start}]
        d['scene_detection']={'status':'failed_after_refine','error':str(e),'scenes':scenes}

    shot_count=len(scenes); cuts=max(0,shot_count-1); durations=[float(s['duration']) for s in scenes]
    d['pacing']={'shot_count':shot_count,'cuts':cuts,'average_shot_length':round(float(np.mean(durations)),3) if durations else round(end-start,3),'median_shot_length':round(float(np.median(durations)),3) if durations else round(end-start,3),'cuts_per_10s':round(cuts/max((end-start)/10.0,1e-9),2)}

    with open(args.evidence,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2)
    with open(out/'scenes.csv','w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['start','end','duration']); w.writeheader(); w.writerows(scenes)

    # Visual proof strips around each detected cut. Ake must inspect them before naming the cut/edit type.
    bdir=out/'scene_boundaries'; bdir.mkdir(exist_ok=True)
    cap=cv2.VideoCapture(args.media)
    offsets=[-0.20,-0.12,-0.05,0.02,0.08,0.16]
    boundary_index=[]
    for i,s in enumerate(scenes[:-1],start=1):
        cut=float(s['end']); items=[]
        for off in offsets:
            t=min(end,max(start,cut+off)); fr=frame_at(cap,t)
            if fr is not None: items.append((t,fr))
        p=bdir/f'cut_{i:03d}_{cut:07.3f}s.jpg'
        if sheet(items,p): boundary_index.append({'cut_number':i,'time':round(cut,3),'evidence_file':str(p.relative_to(out))})
    cap.release()
    with open(out/'scene_boundary_index.json','w',encoding='utf-8') as f: json.dump(boundary_index,f,ensure_ascii=False,indent=2)
    print(json.dumps({'scene_status':d['scene_detection']['status'],'shot_count':shot_count,'cuts':cuts,'boundary_strips':len(boundary_index)},ensure_ascii=False))

if __name__=='__main__': main()
