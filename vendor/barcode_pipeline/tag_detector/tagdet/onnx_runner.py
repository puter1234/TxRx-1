"""CPU ONNX Runtime adapter for exported YOLO26 end-to-end [B,N,6] output."""
import ast
import time
import numpy as np
import onnxruntime as ort
from ultralytics.engine.results import Results
from .geometry import letterbox

class OnnxRunner:
    def __init__(self,path,threads=4):
        opts=ort.SessionOptions(); opts.intra_op_num_threads=threads; opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.input_name=self.session.get_inputs()[0].name
        meta=self.session.get_modelmeta().custom_metadata_map
        self.names=ast.literal_eval(meta.get('names',"{0:'label'}"))
        self.names={int(k):str(v) for k,v in self.names.items()}

    def predict(self,images,imgsz=960,conf=.25,device='cpu',half=False,verbose=False,rect=False,max_det=100,**kwargs):
        if device!='cpu' or half: raise ValueError('This controlled ONNX adapter is CPU FP32 only')
        images=images if isinstance(images,list) else [images]
        t=time.perf_counter(); transformed=[letterbox(im,imgsz) for im in images]
        x=np.stack([im[:,:,::-1].transpose(2,0,1) for im,_ in transformed]).astype(np.float32)/255.
        x=np.ascontiguousarray(x); prep=(time.perf_counter()-t)*1000
        t=time.perf_counter(); raw=self.session.run(None,{self.input_name:x})[0]; infer=(time.perf_counter()-t)*1000
        if raw.ndim!=3 or raw.shape[2]!=6: raise ValueError(f'Expected end-to-end YOLO26 [B,N,6], got {raw.shape}')
        t=time.perf_counter(); results=[]
        for im,(_,transform),pred in zip(images,transformed,raw):
            pred=pred[np.isfinite(pred).all(1)&(pred[:,4]>=conf)].copy()
            pred=pred[np.argsort(-pred[:,4])][:max_det]
            if len(pred):
                pred[:,:4]=transform.inverse(pred[:,:4]); h,w=im.shape[:2]
                pred[:,[0,2]]=np.clip(pred[:,[0,2]],0,w); pred[:,[1,3]]=np.clip(pred[:,[1,3]],0,h)
            results.append(Results(im,path='',names=self.names,boxes=pred))
        post=(time.perf_counter()-t)*1000
        for r in results: r.speed={'preprocess':prep/len(images),'inference':infer/len(images),'postprocess':post/len(images)}
        return results
