"""The add-on's own stand-ins for the shared textures of the animated effects, made with numpy, for whoever doesn't
have the game's (FModel's PaperMan\\Effects folder). Alike, not copies: drawn from noise, cells and gradients. The
noises tile. V is measured from the top of the image, as the game does.
"""
import bpy
import numpy as np

N = 256


def grid():
    """u, v of each pixel."""
    k = (np.arange(N) + 0.5) / N
    return np.meshgrid(k, k)


def step(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def noise(seed, top, low=1):
    """Smooth tiling noise, 0..1: random waves of `low` to `top` cycles per tile."""
    rng, (u, v) = np.random.default_rng(seed), grid()
    out = np.zeros((N, N))
    for fx in range(-top, top + 1):
        for fy in range(top + 1):
            f = np.hypot(fx, fy)
            if low <= f <= top:
                out += rng.normal() / f * np.cos(2 * np.pi * (fx * u + fy * v + rng.random()))
    return (out - out.min()) / (out.max() - out.min())


def cells(seed, count):
    """Tiling cells: (distance to the nearest point, distance to the border between cells)."""
    rng, (u, v) = np.random.default_rng(seed), grid()
    d = []
    for px, py in rng.random((count, 2)):
        dx, dy = np.abs(u - px), np.abs(v - py)
        d.append(np.hypot(np.minimum(dx, 1 - dx), np.minimum(dy, 1 - dy)))
    d = np.sort(np.array(d), axis=0)
    return d[0], d[1] - d[0]


def blob(cu, cv, ru, rv, angle=0.0):
    """Distance to an ellipse's centre, 1 at its rim."""
    u, v = grid()
    c, s = np.cos(angle), np.sin(angle)
    x, y = u - cu, v - cv
    return np.hypot((x * c + y * s) / ru, (y * c - x * s) / rv)


def lava():
    near, border = cells(3, 14)
    return 0.75 * step(near, 0.0, 0.2) + 0.25 * step(0.09 - border, 0.0, 0.09)


def web():
    _, border = cells(8, 18)
    return np.clip(0.75 * noise(5, 4) * step(0.22 - border, 0.0, 0.2) + step(0.03 - border, 0.0, 0.03) * 0.5 * noise(6, 3), 0, 1)


def stars():
    rng, (u, v) = np.random.default_rng(11), grid()
    out = 0.12 * noise(12, 4)
    for x, y, r in rng.random((130, 3)):
        dx, dy = np.abs(u - x), np.abs(v - y)
        out += (0.3 + 0.9 * r) * np.exp(-((np.minimum(dx, 1 - dx) ** 2 + np.minimum(dy, 1 - dy) ** 2) / (0.0012 + 0.003 * r ** 4) ** 1.0) * 60)
    return np.clip(out, 0, 1)


def ridges():
    return np.clip(0.35 * noise(21, 3) + 0.8 * (1 - np.abs(2 * noise(22, 4) - 1)) ** 6, 0, 1)


def rainbow():
    k = noise(31, 3) * 2.5
    return np.stack([0.5 + 0.5 * np.cos(2 * np.pi * (k + o)) for o in (0.0, 0.33, 0.67)], axis=-1)


def ribbon_bands():
    """R the bright edges, G and B the body."""
    v = grid()[1]
    d = np.minimum(v, 1 - v)
    edge = np.exp(-((d - 0.115) / 0.008) ** 2) + 0.25 * step(0.115 - d, -0.12, 0.0) * (d > 0.1) + 0.2 * (d < 0.1)
    return np.stack([np.clip(edge, 0, 1), step(d, 0.0, 0.1), step(d, 0.098, 0.102)], axis=-1)


def wavy_lines():
    u, v = grid()
    return step(0.5 + 0.5 * np.sin(2 * np.pi * (45 * v + 3 * (noise(41, 2) - 0.5) * 4)), 0.35, 0.65)


def silhouette():
    """Bai Mo's scarf end: the part of it left over, ragged."""
    return step(1.0 - blob(0.62, 0.52, 0.36, 0.16, -0.85) + 0.25 * (noise(51, 6) - 0.5), 0.0, 0.05)


def scarf_mask():
    """R what resists the burning (along the scarf), G the noise that pushes it."""
    along = np.exp(-(blob(0.61, 0.5, 0.42, 0.075, -0.85) ** 2) * 1.3)
    return np.stack([along, web(), along], axis=-1)


def flame_mask():
    """Where Flavia's flames glow: a soft patch over them."""
    return 0.8 * np.clip(1.15 - blob(0.79, 0.46, 0.07, 0.2, 0.15), 0, 1)


OWN = {
    "T_Noise_rk_009": lava, "T_c_Fragrans_noise_3": web, "T_Noise_YYM_002": lambda: 0.2 + 0.6 * noise(61, 5),
    "T_Noise_5042_1": lambda: noise(62, 5), "T_Noise_MM_6": stars, "T_Noise_Ljc_033": ridges, "T_Zz_143": rainbow,
    "T_Zz_2162_RGB": ribbon_bands, "T_Mask_Cbn_003": lambda: np.exp(-(((grid()[0] - 0.5) / 0.07) ** 2)) + 0.3 * step(0.4 - np.abs(grid()[0] - 0.5), 0.0, 0.4),
    "T_mask_qwh_04": lambda: step(1 - blob(0.5, 0.5, 0.38, 0.38), 0.0, 1.0),
    "T_Mask_2001": lambda: step(0.5 - np.maximum(np.abs(grid()[0] - 0.5), np.abs(grid()[1] - 0.5)), 0.02, 0.12),
    "T_Mask_Wcc_010": flame_mask, "T_Trail_LKL_031": wavy_lines, "T_Mask_LK_065": lambda: step(1 - grid()[0], 0.0, 0.06),
    "T_Object_NB_008": silhouette, "T_Mask_LK_027": silhouette, "T_Object_NB_009": scarf_mask,
}
CUTOUT = ("T_Mask_LK_027",)  # the shape goes in the alpha, the colour is white


def make(name, colorspace):
    """The stand-in for texture `name` as an image packed in the .blend, or None. One per colour space."""
    if name not in OWN:
        return None
    key = f"ST Own {name} {colorspace}"
    img = bpy.data.images.get(key)
    if img:
        return img
    a = np.asarray(OWN[name]()).clip(0.0, 1.0)
    px = np.ones((N, N, 4), np.float32)
    if name in CUTOUT:
        px[..., 3] = a
    else:
        px[..., :3] = a if a.ndim == 3 else a[..., None]
    img = bpy.data.images.new(key, N, N, alpha=True)
    img.colorspace_settings.name = colorspace
    img.alpha_mode = "CHANNEL_PACKED"
    img.pixels.foreach_set(px[::-1].ravel())  # rows from the bottom
    img.update()
    img.pack()
    return img
