from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


ASSET_DIR = Path(__file__).resolve().parents[1] / "pictures_transparent"


def character_asset_path(character_id, pose):
    return ASSET_DIR / f"{character_id}_{pose}.png"


def clear_character_asset_cache():
    load_character_image.cache_clear()


@lru_cache(maxsize=64)
def load_character_image(character_id, pose, flip=False):
    path = character_asset_path(character_id, pose)
    if not path.exists():
        return None
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim != 3:
        return None
    if image.shape[2] == 3:
        alpha = np.full(image.shape[:2] + (1,), 255, dtype=np.uint8)
        image = np.dstack([image, alpha])
    elif image.shape[2] != 4:
        return None
    if flip:
        image = cv2.flip(image, 1)
    return image


def alpha_blend_bgra(frame, sprite, bottom_center, max_height, max_width=None):
    if sprite is None or sprite.ndim != 3 or sprite.shape[2] != 4:
        return False
    if max_height <= 0:
        return False

    src_h, src_w = sprite.shape[:2]
    if src_h <= 0 or src_w <= 0:
        return False
    scale = max_height / float(src_h)
    if max_width is not None and max_width > 0:
        scale = min(scale, max_width / float(src_w))
    target_w = max(1, int(round(src_w * scale)))
    target_h = max(1, int(round(src_h * scale)))
    resized = cv2.resize(sprite, (target_w, target_h), interpolation=cv2.INTER_AREA)

    cx, by = int(round(bottom_center[0])), int(round(bottom_center[1]))
    x1 = cx - target_w // 2
    y1 = by - target_h
    x2 = x1 + target_w
    y2 = y1 + target_h

    frame_h, frame_w = frame.shape[:2]
    clip_x1 = max(0, x1)
    clip_y1 = max(0, y1)
    clip_x2 = min(frame_w, x2)
    clip_y2 = min(frame_h, y2)
    if clip_x1 >= clip_x2 or clip_y1 >= clip_y2:
        return False

    sprite_x1 = clip_x1 - x1
    sprite_y1 = clip_y1 - y1
    sprite_x2 = sprite_x1 + (clip_x2 - clip_x1)
    sprite_y2 = sprite_y1 + (clip_y2 - clip_y1)

    patch = resized[sprite_y1:sprite_y2, sprite_x1:sprite_x2]
    alpha = patch[:, :, 3:4].astype(np.float32) / 255.0
    if float(alpha.max()) <= 0.0:
        return False

    foreground = patch[:, :, :3].astype(np.float32)
    background = frame[clip_y1:clip_y2, clip_x1:clip_x2].astype(np.float32)
    frame[clip_y1:clip_y2, clip_x1:clip_x2] = (
        foreground * alpha + background * (1.0 - alpha)
    ).astype(np.uint8)
    return True


def draw_character_sprite(
    frame,
    character_id,
    pose,
    bottom_center,
    max_height,
    max_width=None,
    flip=False,
):
    image = load_character_image(character_id, pose, flip=flip)
    if image is None and pose != "normal":
        image = load_character_image(character_id, "normal", flip=flip)
    return alpha_blend_bgra(frame, image, bottom_center, max_height, max_width)
