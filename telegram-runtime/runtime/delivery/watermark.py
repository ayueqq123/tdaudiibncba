"""Media watermark removal for the delivery path (§4.3 copy-mode).

`clean_bytes(data, name, mode, mask)`:
- mode "off"   → passthrough
- mode "mask"  → fixed rect `mask`="x,y,w,h" (fractions 0-1) removed
- mode "auto"  → detect edge-band watermark text via OCR, inpaint images /
                 ffmpeg delogo videos

Heavy deps are optional and lazily imported — missing cv2/onnx/ffmpeg just
returns the original bytes so delivery never breaks over cosmetics.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

log = logging.getLogger(__name__)

_cv2 = None
_np = None
_ocr = None

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
_VID_EXTS = (".mp4", ".mov", ".mkv", ".webm")
_EDGE_BAND = 0.25  # auto 模式只把落在边缘 25% 带内的 OCR 文本当水印


def _cv2_np():
    global _cv2, _np
    if _cv2 is None:
        try:
            import cv2
            import numpy as np

            _cv2, _np = cv2, np
        except ImportError:
            _cv2, _np = False, False
    return _cv2, _np


def _ocr_engine():
    global _ocr
    if _ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr = RapidOCR()
        except Exception as exc:  # noqa: BLE001 — optional dep, degrade silently
            log.warning("rapidocr unavailable, auto watermark detect off: %r", exc)
            _ocr = False
    return _ocr


def _mask_boxes(mask: str | None, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """mask="x,y,w,h"(0-1) -> [(px,py,pw,ph)];支持逗号分隔多个区域。"""
    if not mask:
        return []
    out = []
    for seg in str(mask).split(";"):
        try:
            x, y, bw, bh = [float(v) for v in seg.split(",")]
            out.append((int(x * w), int(y * h), int(bw * w), int(bh * h)))
        except ValueError:
            continue
    return out


def _auto_boxes(img, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """OCR 文本框落在边缘带内 → 视为水印文字。"""
    ocr = _ocr_engine()
    if not ocr:
        return []
    result, _ = ocr(img)
    if not result:
        return []
    boxes = []
    for item in result:
        try:
            box, _txt, conf = item[0], item[1], item[2]
            if float(conf) < 0.5:
                continue
        except (TypeError, ValueError, IndexError):
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if (x0 < w * _EDGE_BAND or x1 > w * (1 - _EDGE_BAND)
                or y0 < h * _EDGE_BAND or y1 > h * (1 - _EDGE_BAND)):
            pad = 8
            x0i, y0i = max(0, int(x0) - pad), max(0, int(y0) - pad)
            boxes.append((x0i, y0i, min(w, int(x1) + pad) - x0i,
                          min(h, int(y1) + pad) - y0i))
    return boxes


def _clean_image(data: bytes, name: str, mode: str, mask: str | None) -> bytes:
    cv2, np = _cv2_np()
    if not cv2:
        return data
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return data
    h, w = img.shape[:2]
    boxes = _mask_boxes(mask, w, h) if mode == "mask" else _auto_boxes(img, w, h)
    if not boxes:
        return data
    m = np.zeros((h, w), np.uint8)
    for x, y, bw, bh in boxes:
        m[y:y + bh, x:x + bw] = 255
    img = cv2.inpaint(img, m, 3, cv2.INPAINT_TELEA)
    ext = os.path.splitext(name)[1].lower() or ".jpg"
    if ext not in _IMG_EXTS:
        ext = ".jpg"
    ok, buf = cv2.imencode(ext, img)
    return buf.tobytes() if ok else data


def _probe_size(path: str) -> tuple[int, int] | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return None


def _clean_video(data: bytes, name: str, mode: str, mask: str | None) -> bytes:
    ext = os.path.splitext(name)[1].lower() or ".mp4"
    boxes: list[tuple[int, int, int, int]] = []
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in" + ext)
        dst = os.path.join(td, "out" + ext)
        with open(src, "wb") as f:
            f.write(data)
        size = _probe_size(src)
        if size is None:
            return data
        w, h = size
        if mode == "mask":
            boxes = _mask_boxes(mask, w, h)
        else:
            # 抽中帧跑 OCR 定位水印
            frame = os.path.join(td, "f.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", src,
                 "-frames:v", "1", frame], timeout=60)
            cv2, np = _cv2_np()
            if cv2 and os.path.exists(frame):
                img = cv2.imread(frame)
                if img is not None:
                    boxes = _auto_boxes(img, w, h)
        if not boxes:
            return data
        vf = ",".join(f"delogo=x={x}:y={y}:w={bw}:h={bh}" for x, y, bw, bh in boxes)
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
             "-c:a", "copy", dst], timeout=600)
        if r.returncode != 0 or not os.path.exists(dst):
            return data
        with open(dst, "rb") as f:
            return f.read()


def clean_bytes(data: bytes, name: str, mode: str, mask: str | None) -> bytes:
    """去水印入口:任何失败都回退原 bytes,不影响投递。"""
    if mode == "off" or not data:
        return data
    ext = os.path.splitext(name or "")[1].lower()
    try:
        if ext in _IMG_EXTS:
            return _clean_image(data, name, mode, mask)
        if ext in _VID_EXTS:
            return _clean_video(data, name, mode, mask)
    except Exception:  # noqa: BLE001 — cosmetic stage must never kill delivery
        log.warning("watermark clean failed name=%s mode=%s", name, mode,
                    exc_info=True)
    return data
