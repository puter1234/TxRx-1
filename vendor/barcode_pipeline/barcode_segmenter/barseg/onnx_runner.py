"""Controlled CPU ONNX inference for YOLO26 end-to-end segmentation exports."""
import ast,time
import numpy as np
import torch
import onnxruntime as ort
from ultralytics.data.augment import LetterBox
from ultralytics.engine.results import Results
from ultralytics.utils import ops

class OnnxRunner:
    def __init__(self,path,threads=4):
        opts=ort.SessionOptions();opts.intra_op_num_threads=threads;opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.input_name=self.session.get_inputs()[0].name
        meta=self.session.get_modelmeta().custom_metadata_map
        self.names={int(k):str(v) for k,v in ast.literal_eval(meta.get('names',"{0:'barcode'}")).items()}

    def predict(self,images,imgsz=640,conf=.25,device='cpu',rect=False,retina_masks=True,max_det=30,**kwargs):
        if device!='cpu' or rect or not retina_masks:raise ValueError('Use CPU, rect=False, retina_masks=True')
        images=images if isinstance(images,list) else [images]
        t=time.perf_counter();letterbox=LetterBox(new_shape=(imgsz,imgsz),auto=False,stride=32)
        x=np.stack([letterbox(image=im)[:,:,::-1].transpose(2,0,1) for im in images])
        x=np.ascontiguousarray(x,dtype=np.float32)/255.;prep=(time.perf_counter()-t)*1000
        t=time.perf_counter();outputs=self.session.run(None,{self.input_name:x});infer=(time.perf_counter()-t)*1000
        det=next((o for o in outputs if o.ndim==3),None);proto=next((o for o in outputs if o.ndim==4),None)
        if det is None or proto is None or det.shape[-1]!=6+proto.shape[1]:
            raise ValueError(f'Expected end-to-end [B,N,6+C] + [B,C,H,W]; got {[o.shape for o in outputs]}')
        t=time.perf_counter();results=[]
        for i,im in enumerate(images):
            rows=det[i];rows=rows[np.isfinite(rows).all(axis=1)&(rows[:,4]>=conf)]
            rows=rows[np.argsort(-rows[:,4])][:max_det].copy()
            pred=torch.from_numpy(rows)
            masks=None
            if len(rows):
                pred[:,:4]=ops.scale_boxes((imgsz,imgsz),pred[:,:4],im.shape)
                masks=ops.process_mask_native(torch.from_numpy(proto[i]),pred[:,6:],pred[:,:4],im.shape[:2])
                keep=masks.sum((-2,-1))>0;pred=pred[keep];masks=masks[keep]
            results.append(Results(im,path='',names=self.names,boxes=pred[:,:6],masks=masks))
        post=(time.perf_counter()-t)*1000
        for r in results:r.speed={'preprocess':prep/len(images),'inference':infer/len(images),'postprocess':post/len(images)}
        return results
