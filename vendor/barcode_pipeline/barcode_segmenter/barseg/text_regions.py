"""Experimental barcode-adjacent text candidates. No OCR or SKU selection.

Uses predicted barcode polygons and original ROI pixels only. Coordinates refer
to pixel centres; the aligned crop is an affine resampling, not perspective
rectification. Both 0/180-degree readings must remain possible for downstream OCR.
"""
import math
import time
import cv2
import numpy as np
from .infer import long_axis, map_points

MAX_TEXT_ANGLE_DEGREES = 5.0


def _parallel_line(group, labels):
    """Measure the printed line, not the axis-aligned rectangle enclosing it.

    Coordinates here have already been rotated to the barcode's long axis.
    Fit glyph bottoms for separate characters; use ink orientation when several
    characters touch and therefore share a connected component.
    """
    if len(group) >= 4:
        points = np.float32([[x + w / 2, y + h] for x, y, w, h, _, _ in group])
        vx, vy, x0, y0 = cv2.fitLine(points, cv2.DIST_HUBER, 0, .01, .01).ravel()
        angle = math.degrees(math.atan2(float(vy), float(vx)))
        residual = np.abs((points[:, 0] - x0) * vy - (points[:, 1] - y0) * vx)
        if np.percentile(residual, 90) > max(2., .25 * np.median([c[3] for c in group])):
            return False
    else:
        x0 = min(c[0] for c in group); x1 = max(c[0] + c[2] for c in group)
        y0 = min(c[1] for c in group); y1 = max(c[1] + c[3] for c in group)
        ys, xs = np.nonzero(np.isin(labels[y0:y1, x0:x1], [c[5] for c in group]))
        if len(xs) < 3:
            return False
        _, (width, height), angle = cv2.minAreaRect(np.column_stack((xs, ys)).astype(np.float32))
        if width < height:
            angle += 90
    angle = (angle + 90) % 180 - 90
    return abs(angle) <= MAX_TEXT_ANGLE_DEGREES


def _points(points, matrix):
    p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    return p @ matrix[:, :2].T + matrix[:, 2]


def _refine_angle(gray, polygon, initial):
    """Estimate the barcode cross-bar direction from gradients inside its mask."""
    x, y, w, h = cv2.boundingRect(np.asarray(polygon, np.float32))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(gray.shape[1], x+w), min(gray.shape[0], y+h)
    if x1-x0 < 5 or y1-y0 < 5:
        return float(initial), 0.0
    g = gray[y0:y1, x0:x1]
    m = np.zeros(g.shape, np.uint8)
    cv2.fillPoly(m, [np.rint(np.asarray(polygon)-[x0, y0]).astype(np.int32)], 255)
    m = cv2.erode(m, np.ones((5, 5), np.uint8)) > 0
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)[m]
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)[m]
    xx, yy, xy = float(gx@gx), float(gy@gy), float(gx@gy)
    coherence = math.hypot(xx-yy, 2*xy) / max(xx+yy, 1e-9)
    angle = math.degrees(.5*math.atan2(2*xy, xx-yy))
    delta = (angle-initial+90) % 180 - 90
    refined = initial+delta if coherence > .3 and abs(delta) <= 25 else initial
    # A rightward axis makes results deterministic, but does not mean text upright.
    return float((refined+90) % 180-90), coherence


def _line_boxes(binary, barcode_width, barcode_height):
    """Group plausible dark glyph components into neighbouring horizontal lines."""
    count, labels, stats, centres = cv2.connectedComponentsWithStats(binary, 8)
    chars = []
    for label, ((x, y, w, h, area), centre) in enumerate(zip(stats[1:], centres[1:]), 1):
        if (area >= 3 and max(3, barcode_height*.10) <= h <= barcode_height*.80
                and w <= barcode_width*1.15 and h/max(w, 1) < 12
                and area/max(w*h,1) < .92):
            chars.append((int(x), int(y), int(w), int(h), centre[1], label))
    lines = []
    for c in sorted(chars, key=lambda a: a[4]):
        matches = [line for line in lines
                   if abs(np.median([a[4] for a in line])-c[4]) < .55*max(c[3], np.median([a[3] for a in line]))]
        if matches:
            min(matches, key=lambda line: abs(np.median([a[4] for a in line])-c[4])).append(c)
        else:
            lines.append([c])
    boxes = []
    for line in lines:
        ordered = sorted(line)
        groups = [[]]
        for c in ordered:
            if groups[-1]:
                previous = groups[-1][-1]
                if c[0]-(previous[0]+previous[2]) > max(barcode_width*.12, c[3]*2.5):
                    groups.append([])
            groups[-1].append(c)
        for group in groups:
            x0 = min(c[0] for c in group); x1 = max(c[0]+c[2] for c in group)
            y0 = min(c[1] for c in group); y1 = max(c[1]+c[3] for c in group)
            if (len(group) >= 4 or any(c[2] > .25*barcode_width for c in group)) and x1-x0 >= .28*barcode_width and (x1-x0)/max(1,y1-y0) >= 4:
                if _parallel_line(group, labels):
                    boxes.append(([x0, y0, x1, y1], len(group)))
    return boxes


def crop_from_quad(image, quad, crop_size):
    """Resample the affine text rectangle directly from ROI or source pixels."""
    w,h=map(int,crop_size)
    if w<2 or h<2:
        raise ValueError('crop_size must be at least 2x2')
    p=np.asarray(quad,np.float32).reshape(4,2)
    matrix=cv2.getAffineTransform(p[[0,1,3]],np.array([[0,0],[w-1,0],[0,h-1]],np.float32))
    return cv2.warpAffine(image,matrix,(w,h),flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))


def extract_text_regions(raw_crop, instances, roi_xyxy=None, source_size=None,
                         target_size=None, keep_images=False):
    """Return unrecognised line candidates above/below each predicted barcode.

    At most one nearest plausible line per side is returned. A candidate can be
    a price or unrelated text; candidates are not decoded product identifiers.
    Pixel arrays are optional and excluded from the JSON-compatible result.
    """
    started = time.perf_counter()
    if raw_crop.dtype != np.uint8 or raw_crop.ndim != 3 or raw_crop.shape[2] != 3:
        raise ValueError('Expected original uint8 BGR crop')
    height, width = raw_crop.shape[:2]
    if roi_xyxy is not None:
        if source_size is None or [width,height] != [roi_xyxy[2]-roi_xyxy[0],roi_xyxy[3]-roi_xyxy[1]]:
            raise ValueError('ROI offset/size must describe the supplied crop')
    elif target_size is not None:
        raise ValueError('target_size requires ROI offset and source_size')
    gray = np.ascontiguousarray(raw_crop[:,:,1])
    # Linear normalization preserves the very small low-light glyph contrast.
    low, high = np.percentile(gray, [1, 99])
    gray = np.clip((gray.astype(np.float32)-low)*255/max(high-low,1),0,255).astype(np.uint8)
    outputs = []
    for barcode_index, inst in enumerate(instances):
        polygon = np.asarray(inst['polygon_roi'],np.float64)
        _, base = long_axis(polygon)
        if base is None:
            continue
        angle, coherence = _refine_angle(gray,polygon,base)
        theta = math.radians(angle)
        rotation = np.array([[math.cos(theta),math.sin(theta)],[-math.sin(theta),math.cos(theta)]])
        aligned = polygon@rotation.T
        left,top = aligned.min(axis=0); right,bottom = aligned.max(axis=0)
        bw,bh = right-left,bottom-top
        if bw < 15 or bh < 5:
            continue
        margin_x = max(8,.14*bw)
        search = max(16,1.25*bh)
        origin = np.array([left-margin_x,top-search])
        matrix = np.column_stack((rotation,-origin))
        inv = cv2.invertAffineTransform(matrix)
        size = (int(math.ceil(bw+2*margin_x)),int(math.ceil(bh+2*search)))
        local = cv2.warpAffine(gray,matrix,size,flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
        valid = cv2.warpAffine(np.full((height,width),255,np.uint8),matrix,size,flags=cv2.INTER_NEAREST)
        bars = np.zeros(local.shape,np.uint8)
        block = max(15,int(bh*.9)//2*2+1)
        ink = cv2.adaptiveThreshold(local,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,block,15)
        local_top,local_bottom = top-origin[1],bottom-origin[1]
        # Segmentation contours can spill into the caption. Recover the physical
        # bar-row envelope from the dense cross-bar gradient in the local image.
        gx=np.abs(cv2.Sobel(local,cv2.CV_32F,1,0,ksize=3))
        xa=int(margin_x+.1*bw);xb=int(margin_x+.9*bw)
        energy=gx[:,xa:xb].mean(axis=1)
        energy=np.convolve(energy,np.ones(3)/3,mode='same')
        ta=max(0,int(local_top-.3*bh));tb=min(size[1],int(local_bottom+.3*bh))
        peak=int(ta+np.argmax(energy[ta:tb]))
        threshold=energy[peak]*.58
        lo=hi=peak
        while lo>ta and energy[lo-1]>threshold:lo-=1
        while hi<tb-1 and energy[hi+1]>threshold:hi+=1
        if .4*bh <= hi-lo+1 <= 1.5*bh:
            local_top=float(lo);local_bottom=float(hi+1)
        # Only mask the refined current barcode envelope: other polygons may
        # overlap its caption. Other bar rows are rejected by glyph geometry.
        bars[:]=0
        bars[max(0,int(local_top)):min(size[1],int(local_bottom)),max(0,int(margin_x-3)):min(size[0],int(margin_x+bw+3))]=255
        ink[(valid==0)|(bars>0)] = 0
        for side,y0,y1 in [('above',0,max(0,int(local_top))),('below',min(size[1],int(math.ceil(local_bottom))),size[1])]:
            if y1-y0 < 3:
                continue
            candidates = _line_boxes(ink[y0:y1],bw,bh)
            # Dark garment/background edges are not dark ink on a light label.
            candidates = [c for c in candidates
                          if np.median(local[y0+c[0][1]:y0+c[0][3],c[0][0]:c[0][2]]) > 60
                          and np.mean(valid[y0+c[0][1]:y0+c[0][3],c[0][0]:c[0][2]]>0) > .98
                          and max(0, min(c[0][2], margin_x+bw)-max(c[0][0], margin_x))
                              / max(1, c[0][2]-c[0][0]) >= .7]
            if not candidates:
                continue
            def distance(candidate):
                box=candidate[0]
                return local_top-(box[3]+y0) if side=='above' else box[1]+y0-local_bottom
            box,component_count = min(candidates,key=distance)
            x0,cy0,x1,cy1 = box; cy0+=y0;cy1+=y0
            glyph_height = cy1-cy0
            px=max(3,int(math.ceil(glyph_height*.35)));py=max(3,int(math.ceil(glyph_height*.30)))
            x0=max(0,x0-px);x1=min(size[0],x1+px)
            cy0=max(0,cy0-py);cy1=min(size[1],cy1+py)
            # Keep glyph padding even near a barcode; truncating at the rough
            # segmentation boundary can remove the top/bottom of characters.
            quad=_points([[x0,cy0],[x1-1,cy0],[x1-1,cy1-1],[x0,cy1-1]],inv)
            candidate={'barcode_index':barcode_index,'side_in_aligned_image':side,
                       'angle_degrees_mod180':angle%180,'angle_gradient_coherence':coherence,
                       'quad_roi':quad.tolist(),'crop_size':[x1-x0,cy1-cy0],
                       'glyph_component_count':component_count,
                       'valid_pixel_fraction':float(np.mean(valid[cy0:cy1,x0:x1]>0)),
                       'orientation_resolved':False,'candidate_rotations_degrees':[0,180],
                       'text':None,'status':'unrecognized_candidate'}
            if roi_xyxy is not None:
                candidate['quad_source']=map_points(quad,roi_xyxy,source_size).tolist()
                if target_size is not None:
                    candidate['quad_target']=map_points(quad,roi_xyxy,source_size,target_size).tolist()
            if keep_images:
                # Unenhanced pixels are retained; no generative restoration.
                raw=crop_from_quad(raw_crop,quad,(x1-x0,cy1-cy0))
                candidate['_raw_crop']=raw
                candidate['_preview_crop']=local[cy0:cy1,x0:x1].copy()
            outputs.append(candidate)
    return {'status':'experimental','regions':outputs,'region_count':len(outputs),
            'scope':'Barcode-adjacent line candidates only; no text recognition or semantic selection',
            'elapsed_ms':(time.perf_counter()-started)*1000}
