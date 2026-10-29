import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['hang_tag', 'adhesive_label']

def read_json(path):
    path = Path(path)
    doc = json.loads(path.read_text(encoding='utf-8-sig'))
    # Bundled manifests explicitly declare a base for portable source paths.
    # Other JSON files and external manifests keep their original semantics.
    if isinstance(doc, dict) and 'source_path_base' in doc:
        base = (path.resolve().parent / doc['source_path_base']).resolve()
        for record in doc.get('images', []):
            source = Path(record['source_path'])
            if not source.is_absolute():
                record['source_path'] = str((base / source).resolve())
    return doc

def write_json(path, value):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def read_image(path):
    im=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)
    if im is None: raise ValueError(f'Cannot decode image: {path}')
    return im

def save_image(path, im):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    ok,encoded=cv2.imencode(p.suffix,im)
    if not ok: raise ValueError(f'Cannot encode: {path}')
    encoded.tofile(p)

def prepare_image(bgr, max_side=1600, gain=3.5):
    """Resize, then fixed green-channel LUT. Same order in preparation/inference.

    Original pixels are never replaced. Return actual x/y resize ratios.
    """
    h,w=bgr.shape[:2]
    r=min(1.0,max_side/max(h,w))
    nw,nh=max(1,round(w*r)),max(1,round(h*r))
    small=cv2.resize(bgr,(nw,nh),interpolation=cv2.INTER_AREA) if (nw,nh)!=(w,h) else bgr
    lut=np.clip(np.arange(256)*gain,0,255).astype(np.uint8)
    green=cv2.LUT(small[:,:,1],lut)
    return cv2.cvtColor(green,cv2.COLOR_GRAY2BGR),(nw/w,nh/h)

def box_iou(a,b):
    a=np.asarray(a,dtype=float).reshape(-1,4); b=np.asarray(b,dtype=float).reshape(-1,4)
    inter=np.maximum(0,np.minimum(a[:,None,2:],b[None,:,2:])-np.maximum(a[:,None,:2],b[None,:,:2])).prod(2)
    area_a=np.maximum(0,a[:,2:]-a[:,:2]).prod(1)
    area_b=np.maximum(0,b[:,2:]-b[:,:2]).prod(1)
    return inter/np.maximum(area_a[:,None]+area_b[None,:]-inter,1e-12)
