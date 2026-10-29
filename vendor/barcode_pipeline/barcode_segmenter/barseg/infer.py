import argparse,time
from pathlib import Path
import cv2,numpy as np,torch
from ultralytics import YOLO
from .common import ROOT,read_json,write_json,read_image,save_image,prepare_roi

def map_points(points, roi_xyxy, source_size, target_size=None):
    """Map ROI pixel-edge coordinates to the source frame or its aligned resize.

    target_size refers to the SAME frame/field of view. A separate camera mode
    is not assumed to align. Segmentation letterbox has already been undone.
    """
    pts=np.asarray(points,dtype=float).reshape(-1,2)
    source=np.array(source_size,dtype=float)
    target=np.array(target_size or source_size,dtype=float)
    if np.any(source<=0) or np.any(target<=0):raise ValueError('Invalid frame size')
    return (pts+np.asarray(roi_xyxy[:2]))*(target/source)

def long_axis(points):
    p=np.asarray(points,np.float32).reshape(-1,2)
    if len(p)<3:return [],None
    rect=cv2.boxPoints(cv2.minAreaRect(p));edges=np.roll(rect,-1,axis=0)-rect
    edge=edges[np.argmax(np.linalg.norm(edges,axis=1))]
    angle=float(np.degrees(np.arctan2(edge[1],edge[0]))%180)
    return rect.astype(float).tolist(),angle

def mask_iou(a,b):
    inter=np.count_nonzero(a&b);union=np.count_nonzero(a|b)
    return inter/union if union else 0.

def deduplicate(instances,threshold=.7):
    kept=[]
    for inst in sorted(instances,key=lambda x:x['confidence'],reverse=True):
        if not any(mask_iou(inst['_mask'],k['_mask'])>threshold for k in kept):kept.append(inst)
    return kept

class BarcodeSegmenter:
    def __init__(self,weights,imgsz=640,conf=.25,threads=4,dedup_iou=.7):
        torch.set_num_threads(threads);cv2.setNumThreads(1)
        if imgsz%32:raise ValueError('imgsz must be divisible by 32')
        if not 0<=conf<=1:raise ValueError('Invalid confidence')
        if Path(weights).suffix=='.onnx':
            from .onnx_runner import OnnxRunner
            self.model=OnnxRunner(weights,threads)
        else:self.model=YOLO(str(weights),task='segment')
        self.imgsz,self.conf,self.dedup_iou=imgsz,conf,dedup_iou

    def predict(self,raw_crop,roi_xyxy=None,source_size=None,target_size=None,keep_masks=False):
        start=time.perf_counter();image=prepare_roi(raw_crop)
        photo_ms=(time.perf_counter()-start)*1000
        result=self.model.predict(image,imgsz=self.imgsz,conf=self.conf,device='cpu',rect=False,
            retina_masks=True,verbose=False,max_det=30)[0]
        t=time.perf_counter();instances=[]
        if result.masks is not None:
            for b,mask,polygon in zip(result.boxes,result.masks.data,result.masks.xy):
                m=mask.cpu().numpy().astype(bool)
                if not m.any() or len(polygon)<3:continue
                quad,angle=long_axis(polygon)
                instances.append({'class_id':0,'confidence':float(b.conf.item()),'bbox_roi_xyxy':b.xyxy[0].cpu().tolist(),
                    'polygon_roi':polygon.astype(float).tolist(),'quad_roi':quad,'long_axis_degrees_mod180':angle,'_mask':m})
        raw_count=len(instances)
        if self.dedup_iou is not None:instances=deduplicate(instances,self.dedup_iou)
        if roi_xyxy is not None:
            if source_size is None:raise ValueError('source_size is required with ROI offset')
            if list(raw_crop.shape[:2][::-1])!=[roi_xyxy[2]-roi_xyxy[0],roi_xyxy[3]-roi_xyxy[1]]:
                raise ValueError('ROI bounds must describe the actual supplied crop')
            for inst in instances:
                for name in ['polygon','quad']:
                    inst[name+'_source']=map_points(inst[name+'_roi'],roi_xyxy,source_size).tolist()
                    if target_size:
                        inst[name+'_target']=map_points(inst[name+'_roi'],roi_xyxy,source_size,target_size).tolist()
        if not keep_masks:
            for inst in instances:inst.pop('_mask')
        extra=(time.perf_counter()-t)*1000
        return {'crop_size':list(raw_crop.shape[:2][::-1]),'imgsz':self.imgsz,'confidence':self.conf,
            'dedup_mask_iou':self.dedup_iou,'raw_instance_count':raw_count,'instances':instances,
            'timing_ms':{'green_gain':photo_ms,**{k:float(v) for k,v in result.speed.items()},
                'geometry_dedup':extra,'total_without_decode':(time.perf_counter()-start)*1000}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);p.add_argument('--weights',default=str(ROOT/'models/barcode.pt'))
    p.add_argument('--out',required=True);p.add_argument('--overlay');p.add_argument('--imgsz',type=int);p.add_argument('--conf',type=float)
    p.add_argument('--roi',nargs=4,type=int);p.add_argument('--source-size',nargs=2,type=int);p.add_argument('--target-size',nargs=2,type=int)
    a=p.parse_args();cfg=read_json(ROOT/'models/deployment.json') if (ROOT/'models/deployment.json').exists() else {}
    raw=read_image(a.image);model=BarcodeSegmenter(a.weights,a.imgsz or cfg.get('imgsz',640),a.conf if a.conf is not None else cfg.get('conf',.25))
    result=model.predict(raw,a.roi,a.source_size,a.target_size)
    write_json(a.out,result)
    if a.overlay:
        im=prepare_roi(raw)
        for inst in result['instances']:
            pts=np.asarray(inst['polygon_roi'],np.int32);cv2.polylines(im,[pts],True,(0,220,255),2)
        save_image(a.overlay,im)
    print(f"{len(result['instances'])} barcodes -> {a.out}")
