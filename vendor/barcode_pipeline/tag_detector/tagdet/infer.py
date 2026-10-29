import argparse
import time
from pathlib import Path
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from .common import read_image,save_image,prepare_image,write_json,box_iou
from .geometry import clip_box,crop_roi,roi_bounds,tile_windows

def deduplicate(detections,threshold=.55):
    remaining=sorted(detections,key=lambda d:d['confidence'],reverse=True); kept=[]
    for d in remaining:
        if any(d['class_id']==k['class_id'] and box_iou([d['bbox_xyxy']],[k['bbox_xyxy']])[0,0]>threshold for k in kept): continue
        kept.append(d)
    return kept

class TagDetector:
    def __init__(self,weights,imgsz=960,conf=.15,device='cpu',half=False,threads=4):
        if imgsz%32: raise ValueError('imgsz must be divisible by 32')
        if not 0<=conf<=1: raise ValueError('Invalid confidence threshold')
        if half and device=='cpu': raise ValueError('FP16 requires a supported accelerator')
        torch.set_num_threads(threads); cv2.setNumThreads(1)
        if Path(weights).suffix.lower()=='.onnx':
            from .onnx_runner import OnnxRunner
            self.model=OnnxRunner(weights,threads)
        else: self.model=YOLO(str(weights),task='detect')
        self.imgsz,self.conf,self.device,self.half=imgsz,conf,device,half

    def predict(self,original,roi_padding=.08,tile_size=None,overlap=.25):
        start=time.perf_counter(); h,w=original.shape[:2]
        windows=tile_windows(w,h,tile_size,overlap) if tile_size else [(0,0,w,h)]
        detections=[]; speed={'preprocess':0.,'inference':0.,'postprocess':0.}; external_ms=0.
        for x,y,x2,y2 in windows:
            t=time.perf_counter(); small,scale=prepare_image(original[y:y2,x:x2])
            external_ms+=(time.perf_counter()-t)*1000
            result=self.model.predict(small,imgsz=self.imgsz,conf=self.conf,device=self.device,half=self.half,verbose=False,rect=False,max_det=100)[0]
            # Ultralytics already undoes its letterbox to the provided small image.
            # Do not undo that padding a second time.
            for b in result.boxes:
                coords=b.xyxy[0]
                coords=coords.cpu().numpy() if isinstance(coords,torch.Tensor) else coords
                coords=coords.astype(float)
                coords[[0,2]]=coords[[0,2]]/scale[0]+x
                coords[[1,3]]=coords[[1,3]]/scale[1]+y
                cid=int(b.cls.item())
                detections.append({'class_id':cid,'class_name':str(result.names[cid]),'confidence':float(b.conf.item()),'bbox_xyxy':clip_box(coords,(w,h))})
            for key in speed: speed[key]+=float(result.speed[key])
        # The tiny-data model can emit overlapping boxes even with its end-to-end
        # head. Keep one high-confidence box per overlapping same-class object.
        dedup_start=time.perf_counter()
        detections=deduplicate(detections)
        dedup_ms=(time.perf_counter()-dedup_start)*1000
        for d in detections:
            crop_box=roi_bounds((w,h),d['bbox_xyxy'],roi_padding)
            d['roi_bbox_xyxy']=crop_box
        return {'image_size':[w,h],'detections':detections,'preprocessing':{'mode':'green_gain','gain':3.5,'max_side':1600},'postprocessing':{'same_class_dedup_iou':.55},'timing_ms':{'green_resize':external_ms,'model_preprocess':speed['preprocess'],'inference':speed['inference'],'model_postprocess':speed['postprocess'],'deduplication':dedup_ms,'pipeline_without_decode':(time.perf_counter()-start)*1000},'tile_count':len(windows)}

    def predict_path(self,path,**kwargs):
        t=time.perf_counter(); im=read_image(path); decode=(time.perf_counter()-t)*1000
        result=self.predict(im,**kwargs); result['timing_ms']['decode']=decode
        result['timing_ms']['pipeline_with_decode']=decode+result['timing_ms']['pipeline_without_decode']
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--weights',required=True); p.add_argument('--image',required=True); p.add_argument('--out',default='prediction.json'); p.add_argument('--crops'); p.add_argument('--imgsz',type=int,default=960); p.add_argument('--conf',type=float,default=.15); p.add_argument('--padding',type=float,default=.08); p.add_argument('--device',default='cpu'); p.add_argument('--half',action='store_true'); p.add_argument('--tile-size',type=int)
    a=p.parse_args(); detector=TagDetector(a.weights,a.imgsz,a.conf,a.device,a.half)
    result=detector.predict_path(a.image,roi_padding=a.padding,tile_size=a.tile_size)
    if a.crops:
        original=read_image(a.image)
        for i,d in enumerate(result['detections']):
            crop,_=crop_roi(original,d['bbox_xyxy'],a.padding); save_image(Path(a.crops)/f'{i:03d}_{d["class_name"]}.png',crop)
    write_json(a.out,result); print(a.out)
