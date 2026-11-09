"""Local pre-gate for the pet-accident detector.

Compares the current frame against a per-camera "clean floor" baseline and
scores how much of the floor changed.  This is deliberately cheap (numpy +
Pillow, a few milliseconds at 480px wide) and is meant to run as a first stage
in front of the VLM.

The score is the area fraction of the largest changed blob that survives the
chroma / luminance filters.  Shadows mostly change luminance, so requiring a
chroma or a sizeable luminance drop (not just a soft gain) rejects most of the
classic false positives the old VLM-only detector fought (light pools, glare,
shadows on shiny tile).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter


@dataclass
class GateResult:
    score: float = 0.0
    blob_area: float = 0.0
    mean_delta_e: float = 0.0
    bbox: tuple[int, int, int, int] | None = None
    detail: str = ""
    ok: bool = False


# --- colour helpers -------------------------------------------------------


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: float32 HxWx3 in 0..255 -> Lab float32 HxWx3."""
    lin = _srgb_to_linear(rgb.astype(np.float32))
    m = np.array(
        [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]],
        dtype=np.float32,
    )
    xyz = lin @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack(
        [
            116.0 * f[..., 1] - 16.0,
            500.0 * (f[..., 0] - f[..., 1]),
            200.0 * (f[..., 1] - f[..., 2]),
        ],
        axis=-1,
    ).astype(np.float32)


def _load_rgb(data: bytes, width: int) -> np.ndarray:
    img = Image.open(BytesIO(data)).convert("RGB")
    h = max(1, round(img.height * width / img.width))
    img = img.resize((width, h), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32)


def _downsample_mask(mask: np.ndarray, factor: int) -> np.ndarray:
    h, w = mask.shape
    h2, w2 = h // factor, w // factor
    if h2 == 0 or w2 == 0:
        return mask
    m = mask[: h2 * factor, : w2 * factor]
    return m.reshape(h2, factor, w2, factor).mean(axis=(1, 3)) > 0.5


def _components(mask: np.ndarray, min_px: int) -> list[tuple[int, int, int, int, int]]:
    """4-neighbour connected components on a small boolean mask."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            pts = []
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(pts) >= min_px:
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                out.append((min(xs), min(ys), max(xs), max(ys), len(pts)))
    return out


def score_change(
    baseline_jpeg: bytes,
    current_jpeg: bytes,
    *,
    width: int = 480,
    ignore_top: float = 0.12,
    de_threshold: float = 12.0,
    chroma_threshold: float = 8.0,
    dark_threshold: float = 20.0,
    min_blob_fraction: float = 0.0008,
    blur: float = 1.4,
) -> GateResult:
    """Return a GateResult describing how much the floor changed.

    ``score`` is the largest surviving blob's area as a fraction of the whole
    frame; ``ok`` means a baseline and current frame were both usable.
    """
    try:
        base = _load_rgb(baseline_jpeg, width)
        cur = _load_rgb(current_jpeg, width)
    except Exception as exc:  # noqa: BLE001 - caller logs the detail
        return GateResult(detail=f"load failed: {exc}")

    if base.shape != cur.shape:
        return GateResult(detail="baseline/current shape mismatch")

    h, w, _ = base.shape
    # Blur first: cheap denoise so JPEG grain and sensor noise do not score.
    base_img = Image.fromarray(base.astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
    cur_img = Image.fromarray(cur.astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
    base = np.asarray(base_img, dtype=np.float32)
    cur = np.asarray(cur_img, dtype=np.float32)

    lab_b = _rgb_to_lab(base)
    lab_c = _rgb_to_lab(cur)
    d = lab_c - lab_b
    delta_e = np.sqrt((d * d).sum(axis=-1))
    chroma = np.sqrt(d[..., 1] ** 2 + d[..., 2] ** 2)

    # "Something appeared": a colour shift, not merely a luminance shift.
    # Shadows are a multiplicative darkening (dL negative, chroma ~0) and must
    # not score, or every passing cloud becomes an accident.
    appeared = chroma > chroma_threshold
    mask = (delta_e > de_threshold) & appeared
    # Ignore very dark areas (night IR noise, unlit corners) in both frames.
    mask &= (lab_c[..., 0] > dark_threshold) & (lab_b[..., 0] > 12.0)
    if ignore_top > 0:
        mask[: int(h * ignore_top), :] = False
    # Ignore a thin border: exposure drift shows up there first.
    border = max(2, w // 80)
    mask[:border, :] = mask[-border:, :] = False
    mask[:, :border] = mask[:, -border:] = False

    small = _downsample_mask(mask, 4)
    total_small = small.size
    comps = _components(small, max(2, int(total_small * min_blob_fraction)))
    if not comps:
        return GateResult(score=0.0, ok=True, detail="no blobs")

    x0, y0, x1, y1, n = max(comps, key=lambda c: c[4])
    frac = n / total_small
    # Mean delta-E inside the winning blob (upscaled bbox, approximate).
    by0, by1 = y0 * 4, min(h, (y1 + 1) * 4)
    bx0, bx1 = x0 * 4, min(w, (x1 + 1) * 4)
    sub = delta_e[by0:by1, bx0:bx1]
    blob_mask = mask[by0:by1, bx0:bx1]
    mean_de = float(sub[blob_mask].mean()) if blob_mask.any() else 0.0

    scale_x = 1920 / w if w else 1.0
    scale_y = 1080 / h if h else 1.0
    bbox = (round(x0 * 4 * scale_x), round(y0 * 4 * scale_y), round(x1 * 4 * scale_x), round(y1 * 4 * scale_y))
    return GateResult(
        score=round(float(frac), 6),
        blob_area=round(float(frac), 6),
        mean_delta_e=round(mean_de, 2),
        bbox=bbox,
        ok=True,
        detail=f"{len(comps)} blob(s), mean dE {mean_de:.1f}",
    )
