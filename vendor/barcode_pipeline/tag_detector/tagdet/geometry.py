"""Coordinates are XYXY continuous pixel edges, image size is (width,height)."""
from dataclasses import dataclass
import math
import cv2
import numpy as np

@dataclass(frozen=True)
class LetterboxTransform:
    original_size: tuple
    resized_size: tuple
    pad_left: int
    pad_top: int
    offset: tuple=(0,0)

    def forward(self, boxes):
        b=np.asarray(boxes,dtype=float).reshape(-1,4).copy()
        w,h=self.original_size; nw,nh=self.resized_size
        b[:,[0,2]]=(b[:,[0,2]]-self.offset[0])*nw/w+self.pad_left
        b[:,[1,3]]=(b[:,[1,3]]-self.offset[1])*nh/h+self.pad_top
        return b

    def inverse(self, boxes):
        b=np.asarray(boxes,dtype=float).reshape(-1,4).copy()
        w,h=self.original_size; nw,nh=self.resized_size
        b[:,[0,2]]=(b[:,[0,2]]-self.pad_left)*w/nw+self.offset[0]
        b[:,[1,3]]=(b[:,[1,3]]-self.pad_top)*h/nh+self.offset[1]
        return b

def letterbox(image, size=960, offset=(0,0)):
    h,w=image.shape[:2]; r=min(size/w,size/h)
    nw,nh=round(w*r),round(h*r)
    left,top=(size-nw)//2,(size-nh)//2
    resized=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_LINEAR)
    out=cv2.copyMakeBorder(resized,top,size-nh-top,left,size-nw-left,cv2.BORDER_CONSTANT,value=(114,114,114))
    return out,LetterboxTransform((w,h),(nw,nh),left,top,offset)

def clip_box(box,size):
    w,h=size
    return [float(np.clip(box[0],0,w)),float(np.clip(box[1],0,h)),float(np.clip(box[2],0,w)),float(np.clip(box[3],0,h))]

def roi_bounds(size,box,padding=.08):
    if padding<0: raise ValueError('padding must be non-negative')
    w,h=size; x1,y1,x2,y2=clip_box(box,(w,h))
    if x2<=x1 or y2<=y1: raise ValueError('Empty or invalid box')
    dx,dy=(x2-x1)*padding,(y2-y1)*padding
    xyxy=[max(0,math.floor(x1-dx)),max(0,math.floor(y1-dy)),min(w,math.ceil(x2+dx)),min(h,math.ceil(y2+dy))]
    return xyxy

def crop_roi(original,box,padding=.08):
    h,w=original.shape[:2]; xyxy=roi_bounds((w,h),box,padding)
    a,b,c,d=xyxy
    return original[b:d,a:c].copy(),xyxy

def tile_windows(width,height,tile_size=2048,overlap=.25):
    if tile_size<=0 or not 0<=overlap<1: raise ValueError('Invalid tiling parameters')
    step=max(1,round(tile_size*(1-overlap)))
    def starts(n):
        return sorted(set(list(range(0,max(1,n-tile_size+1),step))+[max(0,n-tile_size)]))
    return [(x,y,min(x+tile_size,width),min(y+tile_size,height)) for y in starts(height) for x in starts(width)]
