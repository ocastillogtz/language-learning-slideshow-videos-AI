"""
utils_image.py
PIL image utilities: compositing, padding, blending, character icons.
"""
import io, logging
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)


def clamp_character_height(img: Image.Image, height_fraction: float, canvas_h: int) -> Image.Image:
    max_h = int(canvas_h * height_fraction)
    w, h  = img.size
    if h <= max_h: return img
    return img.resize((int(w * max_h / h), max_h), Image.LANCZOS)


def composite_scene(background_path, left_char_path, right_char_path, output_path, cfg):
    """
    Paste left_char on left half and right_char on right half over background.
    Both bottom-anchored. Returns output_path.
    """
    cw = cfg.get("canvas_w", 1024); ch = cfg.get("canvas_h", 1536)
    bg = _scale_to_fill(Image.open(background_path).convert("RGBA"), cw, ch)
    canvas = bg.copy(); half = cw // 2

    for char_path, x_start in [(left_char_path, 0), (right_char_path, half)]:
        if not char_path or not Path(char_path).exists(): continue
        char = Image.open(char_path).convert("RGBA")
        cw2, ch2 = char.size
        px = x_start + max(0, (half - cw2) // 2)
        py = max(0, ch - ch2)
        canvas.alpha_composite(char, dest=(px, py))
        logger.debug(f"[composite] {Path(char_path).name} at ({px},{py})")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG")
    logger.info(f"[composite] Saved: {output_path}")
    return output_path


def _scale_to_fill(img, tw, th):
    w,h = img.size; scale=max(tw/w,th/h)
    nw,nh = int(w*scale),int(h*scale)
    img = img.resize((nw,nh),Image.LANCZOS)
    return img.crop(((nw-tw)//2,(nh-th)//2,(nw-tw)//2+tw,(nh-th)//2+th))


def pad_image_to_frame(img: Image.Image, cfg: dict) -> Image.Image:
    W,H = cfg["target_w"],cfg["target_h"]
    br  = cfg["margin_blur_radius"]; blend=cfg["blend_px"]
    sw,sh = img.size

    # Landscape canvas + portrait illustration (reading_together horizontal long
    # video): show the FULL 9:16 illustration flush against the right edge, and
    # fill the remaining width with a blurred, centered, expanded copy of the
    # same illustration.
    if W > H and sh > sw:
        return _portrait_in_landscape(img, W, H, br, blend)

    scale=W/sw; nh=int(sh*scale)
    img = img.resize((W,nh),Image.LANCZOS)
    if nh>=H: return img.crop((0,0,W,H))
    bgs=H/sh; bgw=int(sw*bgs); bg=img.resize((bgw,H),Image.LANCZOS)
    if bgw>W: bg=bg.crop(((bgw-W)//2,0,(bgw-W)//2+W,H))
    else:
        c=Image.new("RGB",(W,H),(0,0,0)); c.paste(bg,((W-bgw)//2,0)); bg=c
    bg=bg.filter(ImageFilter.GaussianBlur(br))
    res=bg.copy(); res.paste(img,(0,0))
    arr=np.array(res,dtype=np.float32); blr=np.array(res.filter(ImageFilter.GaussianBlur(br)),dtype=np.float32)
    for i in range(blend):
        y=nh-1+i
        if 0<=y<H: arr[y]=(1-i/blend)*blr[y]+(i/blend)*arr[y]
    return Image.fromarray(arr.astype(np.uint8))


def _portrait_in_landscape(img: Image.Image, W: int, H: int,
                           blur_radius: int, blend: int) -> Image.Image:
    """
    Compose a portrait (9:16) illustration onto a landscape (16:9) canvas:

      * Foreground: the full illustration scaled to the canvas height and pinned
        flush against the RIGHT edge (nothing cropped).
      * Background: a centered, expanded ("cover") copy of the same illustration
        scaled to fill the whole canvas, then Gaussian-blurred.

    A short horizontal feather softens the seam where the sharp foreground meets
    the blurred background.
    """
    img = img.convert("RGB")

    # Foreground — fit entire illustration to the canvas height.
    fg_scale = H / img.height
    fg_w     = max(1, int(round(img.width * fg_scale)))
    fg       = img.resize((fg_w, H), Image.LANCZOS)
    if fg_w > W:                      # unusually wide portrait — clamp to canvas
        left = (fg_w - W) // 2
        fg   = fg.crop((left, 0, left + W, H))
        fg_w = W

    # Background — centered, expanded copy that covers the full canvas, blurred.
    bg = _scale_to_fill(img, W, H).filter(ImageFilter.GaussianBlur(blur_radius))

    fg_x = W - fg_w
    res  = bg.copy()
    res.paste(fg, (fg_x, 0))

    # Feather the left seam of the foreground into the blurred background.
    if blend > 0 and fg_x > 0:
        arr = np.array(res, dtype=np.float32)
        blr = np.array(res.filter(ImageFilter.GaussianBlur(blur_radius)), dtype=np.float32)
        span = min(blend, fg_w)
        for i in range(span):
            x = fg_x + i
            if 0 <= x < W:
                a = i / span
                arr[:, x] = (1 - a) * blr[:, x] + a * arr[:, x]
        res = Image.fromarray(arr.astype(np.uint8))

    return res


def blur_image(img, radius): return img.filter(ImageFilter.GaussianBlur(radius))
def pil_to_numpy(img): return np.array(img.convert("RGB"))
def bytes_to_pil(data, mode="RGBA"): return Image.open(io.BytesIO(data)).convert(mode)


def make_corner_icon_clip(icon_rel_path, assets_dir, size, x, y, duration_s):
    """
    Build a static icon overlay (e.g. the reading "book" cue) pinned to a corner.

    `icon_rel_path` is a path RELATIVE to assets_dir (e.g. "icons/book.png"); a
    leading "assets/" is tolerated and stripped. The icon keeps its aspect ratio
    and is scaled to fit within a size×size box. Returns an ImageClip positioned at
    (x, y), or None if the file is missing.
    """
    from moviepy.editor import ImageClip
    if not icon_rel_path:
        return None
    p = Path(icon_rel_path)
    if p.parts and p.parts[0] == "assets":
        p = Path(*p.parts[1:])
    fp = assets_dir / p
    if not fp.exists():
        logger.warning(f"Pre-pause icon not found: {fp}")
        return None
    icon = Image.open(fp).convert("RGBA")
    w, h = icon.size
    scale = min(size / w, size / h)
    icon = icon.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return (ImageClip(np.array(icon), ismask=False)
            .set_duration(duration_s).set_position((x, y)))


def make_icon_clip(character, characters_data, assets_dir, duration_s, cfg):
    from moviepy.editor import ImageClip
    tr = characters_data.get(character,{}).get("thumbnail")
    if not tr: return None
    p = Path(tr)
    if p.parts[0]=="assets": p=Path(*p.parts[1:])
    fp = assets_dir/p
    if not fp.exists(): logger.warning(f"Thumbnail not found: {fp}"); return None
    sz=cfg["icon_size"]
    thumb=Image.open(fp).convert("RGBA").resize((sz,sz),Image.LANCZOS)
    mask=Image.new("L",(sz,sz),0); d=ImageDraw.Draw(mask); d.ellipse((0,0,sz-1,sz-1),fill=255)
    thumb.putalpha(mask)
    return (ImageClip(np.array(thumb),ismask=False)
            .set_duration(duration_s).set_position((cfg["icon_x"],cfg["icon_y"])))
