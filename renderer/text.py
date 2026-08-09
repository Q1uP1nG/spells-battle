from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only on minimal installs
    Image = None
    ImageDraw = None
    ImageFont = None
    PIL_AVAILABLE = False


FONT_CANDIDATES = {
    "title": [
        r"C:\Windows\Fonts\georgiab.ttf",
        r"C:\Windows\Fonts\cambriaz.ttf",
        r"C:\Windows\Fonts\ANTQUAB.TTF",
        r"C:\Windows\Fonts\timesbd.ttf",
    ],
    "body": [
        r"C:\Windows\Fonts\georgia.ttf",
        r"C:\Windows\Fonts\cambria.ttf",
        r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\simkai.ttf",
    ],
}

TEXT_CACHE_SIZE = 512


def select_font_path(face="body"):
    for candidate in FONT_CANDIDATES.get(face, FONT_CANDIDATES["body"]):
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def _clamp_color(color):
    return tuple(max(0, min(255, int(channel))) for channel in color)


@lru_cache(maxsize=32)
def _load_font(face, size):
    if not PIL_AVAILABLE:
        return None
    path = select_font_path(face)
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(path, size=size)


def _font_bbox(font, text, anchor=None):
    try:
        if anchor is None:
            return font.getbbox(text)
        return font.getbbox(text, anchor=anchor)
    except TypeError:
        return font.getbbox(text)


@lru_cache(maxsize=TEXT_CACHE_SIZE)
def _measure_text_cached(text, size, face):
    if PIL_AVAILABLE:
        font = _load_font(face, size)
        bbox = _font_bbox(font, text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    scale = max(0.35, size / 32.0)
    (width, height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    return width, height


def measure_text(text, size=22, face="body"):
    return _measure_text_cached(str(text), int(size), str(face))


@lru_cache(maxsize=TEXT_CACHE_SIZE)
def _render_text_bitmap(text, size, face, color, anchor):
    font = _load_font(face, size)
    bbox = _font_bbox(font, text, anchor=anchor)
    width = max(1, int(bbox[2] - bbox[0]))
    height = max(1, int(bbox[3] - bbox[1]))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_pos = (-int(bbox[0]), -int(bbox[1]))
    try:
        if anchor is None:
            draw.text(draw_pos, text, font=font, fill=tuple(color) + (255,))
        else:
            draw.text(draw_pos, text, font=font, fill=tuple(color) + (255,), anchor=anchor)
    except Exception:
        draw.text(draw_pos, text, font=font, fill=tuple(color) + (255,))

    bitmap = np.asarray(image, dtype=np.uint8)
    return (
        bitmap[:, :, :3].copy(),
        bitmap[:, :, 3].copy(),
        int(bbox[0]),
        int(bbox[1]),
    )


def _blend_bitmap(frame, bitmap, pos):
    rgb, alpha, offset_x, offset_y = bitmap
    x = int(pos[0]) + offset_x
    y = int(pos[1]) + offset_y
    h, w = alpha.shape[:2]
    frame_h, frame_w = frame.shape[:2]

    dst_x1 = max(0, x)
    dst_y1 = max(0, y)
    dst_x2 = min(frame_w, x + w)
    dst_y2 = min(frame_h, y + h)
    if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
        return

    src_x1 = dst_x1 - x
    src_y1 = dst_y1 - y
    src_x2 = src_x1 + (dst_x2 - dst_x1)
    src_y2 = src_y1 + (dst_y2 - dst_y1)

    patch_rgb = rgb[src_y1:src_y2, src_x1:src_x2].astype(np.uint32)
    patch_alpha = alpha[src_y1:src_y2, src_x1:src_x2].astype(np.uint32)
    if not np.any(patch_alpha):
        return

    roi = frame[dst_y1:dst_y2, dst_x1:dst_x2]
    inv_alpha = 255 - patch_alpha
    blended = (
        roi.astype(np.uint32) * inv_alpha[:, :, None]
        + patch_rgb * patch_alpha[:, :, None]
        + 127
    ) // 255
    roi[:] = blended.astype(np.uint8)


def clear_text_cache():
    _measure_text_cached.cache_clear()
    if PIL_AVAILABLE:
        _render_text_bitmap.cache_clear()


def draw_text(frame, text, pos, size=22, color=(245, 245, 245), face="body"):
    if PIL_AVAILABLE:
        bitmap = _render_text_bitmap(
            str(text),
            int(size),
            str(face),
            _clamp_color(color),
            None,
        )
        _blend_bitmap(frame, bitmap, pos)
        return

    scale = max(0.35, size / 32.0)
    cv2.putText(
        frame,
        str(text),
        tuple(np.int32(pos)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        1,
        cv2.LINE_AA,
    )


def draw_cv_text(frame, text, org, scale=0.5, color=(245, 245, 245), face="body", thickness=1):
    """Draw text with OpenCV-style baseline coordinates using the serif PIL path.

    Existing renderers were laid out with cv2.putText, where ``org`` is the
    lower-left baseline. Keeping that convention lets us swap the font renderer
    without rewriting every coordinate by hand.
    """
    size = max(10, int(round(scale * 34)))
    if PIL_AVAILABLE:
        bitmap = _render_text_bitmap(
            str(text),
            size,
            str(face),
            _clamp_color(color),
            "ls",
        )
        _blend_bitmap(frame, bitmap, org)
        return

    cv2.putText(
        frame,
        str(text),
        tuple(np.int32(org)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def draw_centered_text(frame, text, x, y, size=22, color=(245, 245, 245), face="body"):
    width, height = measure_text(text, size=size, face=face)
    draw_text(frame, text, (int(x - width / 2), int(y - height / 2)), size, color, face)
