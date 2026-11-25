"""Toon shading and lighting: materials from FModel's JSON/PNG, light/head vectors, the lighting
panel (HSV wheels + sun handle) and the inverted-hull outline.

The shader reuses Gacha Setup's idea of light/head vectors stored as mesh attributes
(lightDir, headForward, headUp).
Textures (channels read off the data and the game's captures): Mask1 = R ramp / matcap index or, in the old
materials, the hair highlight; G and A where and how much matcap; B emission. Mask2 (PBR) = R metal,
G roughness, B specular, A how much environment is reflected; Mask2(0-1) is its fixed value without a texture.
MixTex (old) = R roughness, G metal, B specular; none = the game's default (1, 0, 0): no highlight.
shortcut: the game's specular formulas aren't in the export (Spec1 / Spec2, the environment
reflection): a GGX highlight with Spec1's curve as its parameters suggest and a plain sky stand in for them. Revisit with captures.
"""
import bpy, os, re, json, contextlib, functools, mathutils
from math import cos, sin, tau  # imported by name: math() below is a node helper
from . import common, paper
from .common import target_mesh, rpt_

SHADOW_TINT = (0.80, 0.70, 0.82, 1.0)


# ---------- file lookup ----------
def index_files(root, exts=(".png", ".json"), prefer=None):
    """One {lower-case file name without extension: [paths]} per extension in `exts`, in one walk.
    Paths under `prefer` (the model's own skin folder) go first: a tree renamed by skin name has no
    Sxxx in its paths for pick() to match."""
    idx = {e: {} for e in exts}
    for d, _, files in os.walk(root):
        for f in files:
            name, e = os.path.splitext(f)
            if e.lower() in idx:
                # case-insensitive: JSONs say T_Aika_body_1_D for the file T_Aika_Body_1_D.png
                idx[e.lower()].setdefault(name.lower(), []).append(os.path.join(d, f))
    if prefer:
        prefer = os.path.normcase(os.path.normpath(prefer)) + os.sep
        for paths in (p for i in idx.values() for p in i.values()):
            paths.sort(key=lambda p: not os.path.normcase(p).startswith(prefer))
    return tuple(idx.values())


# folders above the model searched for its textures: 7 reaches a shared Texturas folder from the deepest
# models of a packaged tree (uemodel\Armas\<Weapon>\<Skin>\Mesh\..., props inside a character's Mesh3D)
TEXTURE_LEVELS = 7
# files: a bigger tree (a user folder, a whole drive) is no texture export and takes minutes to walk.
# shortcut: a model with a texture missing from a shallow folder (Downloads\x) may walk up to this many
# files of the user folder (~10 s on a cold disk) before giving up; lower it if that bites.
WALK_CAP = 25000


def texture_names(obj, weapon=False):
    """Lower-case names of the textures `obj`'s materials use, from the bundled material table."""
    names = set()
    for slot in obj.material_slots:
        if slot.material and not slot.material.name.endswith(OUTLINE_SUFFIX):
            base = re.sub(r"\.\d{3}$", "", slot.material.name)
            data = bundled_material(base, weapon_skin(base) if weapon else skin_of(base, ""), "") or {}
            names |= {v["ObjectName"].split("'")[1].lower() for v in data.get("Textures", {}).values() if v}
    return names


def texture_root(path, names, ext=".png"):
    """The folder around a model file that holds its textures: its own folder first, then each parent
    (up to TEXTURE_LEVELS, never a drive root), keeping the nearest one that finds the most of `names`
    (lower-case file names without extension; any file of `ext` when empty). None if none has any.
    Weapons look for their material JSONs (ext=".json"): no bundled data says which textures they use."""
    best, best_n, stale = None, 0, 0
    folder = os.path.dirname(os.path.abspath(path))
    for _ in range(TEXTURE_LEVELS + 1):
        if os.path.dirname(folder) == folder:
            break  # a drive root
        found, seen = set(), 0
        for _d, _, files in os.walk(folder):
            seen += len(files)
            if seen > WALK_CAP:
                return best
            found |= {n for n in (os.path.splitext(f)[0].lower() for f in files if f.lower().endswith(ext))
                      if not names or n in names}
            if found and (not names or found >= names):
                return folder  # all of them (or, with no names, any file): nothing nearer was better
        stale = stale + 1 if best and len(found) <= best_n else 0
        if stale == 2:
            break  # two levels up found nothing new: the rest is missing from the export, not further up
        if len(found) > best_n:
            best, best_n = folder, len(found)
        folder = os.path.dirname(folder)
    return best


MISSING = "falta textura: "
NO_DATA = "sin datos de material, se deja igual"  # report entry of a material with no JSON nor bundled data  # report entry of a material whose texture file isn't in the folder


def missing_textures(report):
    """Materials of a shading report left untouched because their texture file wasn't found."""
    return [k for k, v in report.items() if isinstance(v, str) and v.startswith(MISSING)]


def source_skin_dir(obj):
    """The skin folder of the model file an object was imported from (the folder holding Mesh2D /
    Mesh3D*), or None."""
    src = obj.get("st_source")
    parts = os.path.normpath(src).split(os.sep) if src else []
    i = next((i for i in range(len(parts) - 1, 0, -1) if re.match(r"(?i)mesh[23]d", parts[i])), None)
    return os.sep.join(parts[:i]) if i else None


def pick(idx, name, skin):
    paths = idx.get(name.lower()) or []
    for p in paths:  # prefer the skin folder the asset belongs to
        if f"{os.sep}{skin}{os.sep}" in p:
            return p
    return paths[0] if paths else None


def skin_of(name, fallback):
    m = re.search(r"_(S\d{3})", name)
    return m.group(1) if m else fallback


def weapon_skin(name):
    m = re.search(r"_(\d{3})(?:_|$)", name)  # MI_Weap_AKM_104_01: skin S104
    return f"S{m.group(1)}" if m else ""


# ---------- node sections (frames) ----------
SECTION_COLORS = {  # frame tint per kind of section
    "in": (0.22, 0.22, 0.22), "light": (0.42, 0.36, 0.14), "color": (0.33, 0.2, 0.38),
    "tex": (0.18, 0.28, 0.42), "out": (0.14, 0.32, 0.18),
}


@contextlib.contextmanager
def section(nt, label, kind, extra=()):
    """Put the nodes created inside the block (plus `extra`) in a titled, coloured frame."""
    before = set(nt.nodes)
    yield
    frame(nt, label, kind, [n for n in nt.nodes if n not in before and n.type != "FRAME"] + list(extra))


def frame(nt, label, kind, nodes):
    if not nodes:
        return None
    fr = nt.nodes.new("NodeFrame")
    fr.label, fr.label_size, fr.shrink = label, 20, True
    fr.use_custom_color, fr.color = True, SECTION_COLORS[kind]
    for n in nodes:
        n.parent = fr  # Blender keeps the node's absolute position
    return fr


def arrange_sections(nt, gap=80):
    """Lay the frames out left to right in creation order (= data flow), so sections never overlap;
    each section keeps its inner layout and height."""
    x = None
    for fr in [n for n in nt.nodes if n.type == "FRAME"]:
        kids = [n for n in nt.nodes if n.parent == fr]
        if not kids:
            continue
        left = min(n.location_absolute.x for n in kids)
        right = max(n.location_absolute.x + n.width for n in kids)
        x = left if x is None else x
        for n in kids:
            n.location_absolute = (n.location_absolute.x + x - left, n.location_absolute.y)
        x += right - left + gap


# ---------- node helpers ----------
def sock(ng, name, io, typ, default=None):
    s = ng.interface.new_socket(name, in_out=io, socket_type=typ)
    if default is not None:
        s.default_value = default
    return s


def node(nt, typ, x, y, **props):
    n = nt.nodes.new(typ)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def attr(nt, name, x, y):
    a = node(nt, "ShaderNodeAttribute", x, y, attribute_type="GEOMETRY", attribute_name=name)
    nrm = node(nt, "ShaderNodeVectorMath", x + 180, y, operation="NORMALIZE")
    nt.links.new(a.outputs["Vector"], nrm.inputs[0])
    return nrm.outputs[0]


def vmath(nt, op, a, b, x, y):
    n = node(nt, "ShaderNodeVectorMath", x, y, operation=op)
    nt.links.new(a, n.inputs[0])
    if b is not None:
        nt.links.new(b, n.inputs[1])
    return n


def math(nt, op, a, b, x, y):
    n = node(nt, "ShaderNodeMath", x, y, operation=op)
    for i, v in enumerate((a, b)):
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        elif v is not None:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def mix_rgb(nt, blend, fac, a, b, x, y, clamp=True):
    n = node(nt, "ShaderNodeMix", x, y, data_type="RGBA", blend_type=blend, clamp_result=clamp)
    for i, v in ((0, fac), (6, a), (7, b)):
        if isinstance(v, (int, float, tuple)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[2]


def soft_step(nt, value, center, softness, x, y):
    lo = math(nt, "SUBTRACT", center, softness, x, y + 80)
    hi = math(nt, "ADD", center, softness, x, y - 80)
    mr = node(nt, "ShaderNodeMapRange", x + 180, y, clamp=True)
    nt.links.new(value, mr.inputs["Value"])
    nt.links.new(lo, mr.inputs["From Min"])
    nt.links.new(hi, mr.inputs["From Max"])
    return mr.outputs["Result"]


def hsv_wheel(nt, a, b, value, x, y):
    """Colour from a point on the lighting panel wheel: angle = hue, radius = saturation."""
    ang = math(nt, "ARCTAN2", b, a, x, y)
    hue = math(nt, "FRACT", math(nt, "DIVIDE", ang, tau, x + 150, y), None, x + 300, y)
    r2 = math(nt, "ADD", math(nt, "MULTIPLY", a, a, x, y - 120), math(nt, "MULTIPLY", b, b, x, y - 200), x + 150, y - 160)
    sat = math(nt, "MINIMUM", math(nt, "SQRT", r2, None, x + 300, y - 160), 1.0, x + 450, y - 160)
    cc = node(nt, "ShaderNodeCombineColor", x + 600, y, mode="HSV")
    nt.links.new(hue, cc.inputs[0])
    nt.links.new(sat, cc.inputs[1])
    nt.links.new(value, cc.inputs[2])
    return cc.outputs[0]


def packed(nt, name, x, y):
    """(colour, alpha) of one of the packed object properties (st_l_*): read from the mesh, so each
    character is lit by its own panel."""
    a = node(nt, "ShaderNodeAttribute", x, y, attribute_type="OBJECT", attribute_name=name)
    return a.outputs["Color"], a.outputs["Alpha"]


def panel_color(nt, name, mode, x, y):
    """One of the panel's colours: RGB from the sidebar, or a rig wheel's picker (x, z, value). Unclamped:
    the value slider goes to 1.5."""
    col, _ = packed(nt, f"st_l_{name}", x, y)
    sep = node(nt, "ShaderNodeSeparateXYZ", x + 180, y)
    nt.links.new(col, sep.inputs[0])
    wheel = hsv_wheel(nt, sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"], x + 360, y)
    return mix_rgb(nt, "MIX", mode, wheel, col, x + 1140, y, clamp=False)


def scaled_softness(nt, softness, x, y):
    """The material's shadow softness times the panel's (kept above 0: a zero range has no transition)."""
    return math(nt, "MAXIMUM", math(nt, "MULTIPLY", softness, packed(nt, "st_l_sharp_shadow", x, y)[1], x + 180, y), 0.0005, x + 360, y)


RAMPS, RAMP_W, RAMP_EDGE = "ST Ramps", 512, 0.53  # RAMP_EDGE: where most ramps turn from shadow to light
RAMP_FILE = "RampTexture2DArray_LAYER{}.png"  # FModel's "Save Texture" of the game's ramps
# the add-on's own shadow colours (sRGB), used without that export: one flat, rounded colour per RampID,
# picked by eye to resemble the game's, with a generic edge
NEUTRAL, LILAC, SKIN, DARK, WARM = (0.85, 0.85, 0.85), (0.82, 0.80, 0.90), (0.96, 0.83, 0.78), (0.50, 0.48, 0.58), (0.88, 0.80, 0.72)
OWN_RAMPS = [
    (1.0, 1.0, 1.0), NEUTRAL, LILAC, NEUTRAL, SKIN, SKIN, LILAC, (1.0, 0.84, 0.85), DARK, WARM, LILAC, (0.55, 0.65, 0.80),
    LILAC, WARM, DARK, WARM, (0.94, 0.89, 0.91), (0.80, 0.65, 0.80), (0.65, 0.45, 0.38), (0.75, 0.68, 0.95),
    (0.78, 0.72, 0.45), (0.88, 0.68, 0.58), SKIN, (0.68, 0.76, 0.95), (0.76, 0.84, 0.94), (0.76, 0.80, 0.95), (0.75, 0.77, 0.80)]


def own_ramps():
    """Pixels of OWN_RAMPS: flat shadow up to the middle, then a short smooth edge to white."""
    pixels = []
    for shadow in OWN_RAMPS:
        for i in range(RAMP_W):
            t = min(max((i / (RAMP_W - 1) - 0.5) / 0.07, 0.0), 1.0)
            t = t * t * (3 - 2 * t)
            pixels += [c + (1 - c) * t for c in shadow] + [1.0]
    return pixels


def game_ramps(char_dir):
    """Pixels of the game's ramps from the user's own FModel export (MaterialMaster\\Character, around the
    character's folder or the one in the preferences), or None if they aren't all there."""
    for root in (common.skin_assets(char_dir) if char_dir and "SkinAssets" in char_dir else None, common.fmodel_root()):
        folder = root and os.path.join(os.path.dirname(root), "MaterialMaster", "Character")
        if not folder or not all(os.path.isfile(os.path.join(folder, RAMP_FILE.format(i))) for i in range(len(OWN_RAMPS))):
            continue
        pixels = []
        for i in range(len(OWN_RAMPS)):
            img = bpy.data.images.load(os.path.join(folder, RAMP_FILE.format(i)), check_existing=False)
            row = list(img.pixels) if img.size[0] == RAMP_W and img.size[1] >= 1 else []
            bpy.data.images.remove(img)
            pixels += row[:RAMP_W * 4]
        if len(pixels) == len(OWN_RAMPS) * RAMP_W * 4:
            return pixels
    return None


def ramp_image(char_dir=None):
    """The shadow ramps, one per row (row 0 at the bottom), shared by every character: the game's once
    found, the add-on's own until then."""
    img = bpy.data.images.get(RAMPS)
    if img and img.get("st_game"):
        return img
    game = game_ramps(char_dir)
    if img and "st_game" in img and not game:
        return img
    img = img or bpy.data.images.new(RAMPS, RAMP_W, len(OWN_RAMPS))
    img.pixels.foreach_set(game or own_ramps())
    img.update()
    img.pack()  # saved in the .blend: it has no file
    img["st_game"] = bool(game)
    return img


def ramp_color(nt, u, ramp_id, softness, x, y):
    """Colour of ramp `ramp_id` at `u` (0 shadow, 1 light). The panel's softness stretches the edge."""
    img = ramp_image()
    u = math(nt, "ADD", math(nt, "DIVIDE", math(nt, "SUBTRACT", u, RAMP_EDGE, x, y), softness, x + 180, y), RAMP_EDGE, x + 360, y)
    row = math(nt, "DIVIDE", math(nt, "ADD", ramp_id, 0.5, x, y - 200), float(img.size[1]), x + 180, y - 200)
    uv = node(nt, "ShaderNodeCombineXYZ", x + 540, y)
    nt.links.new(u, uv.inputs[0])
    nt.links.new(row, uv.inputs[1])
    t = node(nt, "ShaderNodeTexImage", x + 900, y, image=img, extension="EXTEND", interpolation="Closest")
    nt.links.new(uv.outputs[0], t.inputs["Vector"])
    return t.outputs["Color"]


def toon_mix(nt, lit, soft, ndl, normal, base, tint, rim, x, y, ramp=None):
    """Lit side = base * sharp lit, shadow side = base * shadow tint * sharp shadow (the toon edge; with a
    `ramp` colour instead of a tint, base * ramp on both); then
    the soft colours (the wide gradient `soft`), the ambient colour over everything and the rim light.
    rim: {RIM_INPUTS name: socket}, or None."""
    with section(nt, "Panel colours (rig wheels or sidebar)", "color"):
        mode = packed(nt, "st_l_sharp_lit", x - 200, y + 600)[1]
        extra = packed(nt, "st_l_soft_lit", x - 200, y + 450)[1]
        scale = packed(nt, "st_l_rim_lit", x - 200, y + 300)[1]
        ambient, sharp_lit, soft_lit, sharp_shadow, soft_shadow, rim_lit, rim_shadow = (
            panel_color(nt, c, mode, x, y + 600 - 250 * i) for i, c in enumerate(COLORS))
    with section(nt, "Light / shadow mix", "color"):
        shadow = mix_rgb(nt, "MULTIPLY", 1.0, base, tint if ramp is None else ramp, x, y - 100)
        col = mix_rgb(nt, "MULTIPLY", 1.0, base if ramp is None else shadow, sharp_lit, x, y + 100)
        col = mix_rgb(nt, "MIX", lit, mix_rgb(nt, "MULTIPLY", 1.0, shadow, sharp_shadow, x + 150, y - 100), col, x + 300, y)
        col = mix_rgb(nt, "MULTIPLY", 1.0, col, mix_rgb(nt, "MIX", soft, soft_shadow, soft_lit, x + 450, y - 200, clamp=False), x + 600, y)
        col = mix_rgb(nt, "MULTIPLY", 1.0, col, ambient, x + 750, y)
    with section(nt, "Rim light", "light"):
        geo = node(nt, "ShaderNodeNewGeometry", x, y - 300)
        nv = math(nt, "ABSOLUTE", vmath(nt, "DOT_PRODUCT", normal, geo.outputs["Incoming"], x + 180, y - 300).outputs["Value"], None, x + 360, y - 300)
        edge = math(nt, "MAXIMUM", math(nt, "SUBTRACT", 1.0, nv, x + 540, y - 300), 0.0, x + 720, y - 300)
        tint = mix_rgb(nt, "MIX", lit, rim_shadow, rim_lit, x + 540, y - 800, clamp=False)
        tint = mix_rgb(nt, "MULTIPLY", 1.0, tint, scale, x + 720, y - 800, clamp=False)
        # "Extra Rim", for the many materials whose JSON has none: mixed in, not added, so it also shows on
        # black cloth and on skin that is already near white
        bright = mix_rgb(nt, "MULTIPLY", 1.0, mix_rgb(nt, "MIX", 0.5, base, (1.0, 1.0, 1.0, 1.0), x + 720, y - 450), tint, x + 900, y - 600, clamp=False)
        col = mix_rgb(nt, "MIX", math(nt, "MULTIPLY", soft_step(nt, edge, 0.55, 0.08, x + 900, y - 450), extra, x + 1260, y - 450), col, bright, x + 1440, y - 450)
        if rim:
            # shortcut: the game's formula isn't in the export; read from the parameters. A third of the
            # rims have scale 0 with intensities up to 8, so the scale can't multiply: it is how much the
            # fresnel (edge ^ exponent) softens an edge band `range` wide. Revisit with captures.
            center = math(nt, "MAXIMUM", math(nt, "MULTIPLY_ADD", rim["Rim Range"], -0.7, x + 720, y - 1050), 0.25, x + 900, y - 1050)
            nt.nodes[-2].inputs[2].default_value = 1.0
            amt = soft_step(nt, edge, center, 0.08, x + 1080, y - 1050)
            fres = math(nt, "MULTIPLY", math(nt, "SUBTRACT", 1.0, math(nt, "POWER", edge, rim["Rim Exponent"], x + 900, y - 1250), x + 1080, y - 1250),
                        rim["Rim Scale"], x + 1260, y - 1250)
            amt = math(nt, "MULTIPLY", amt, math(nt, "SUBTRACT", 1.0, fres, x + 1440, y - 1250), x + 1620, y - 1050)
            # dot scale: 0 = all around, 1 = fades out away from the light
            away = math(nt, "MULTIPLY", math(nt, "MULTIPLY", math(nt, "SUBTRACT", 1.0, ndl, x + 900, y - 1450), 0.5, x + 1080, y - 1450),
                        rim["Rim Dot Scale"], x + 1260, y - 1450)
            away = math(nt, "MAXIMUM", math(nt, "SUBTRACT", 1.0, away, x + 1440, y - 1450), 0.0, x + 1620, y - 1450)
            amt = math(nt, "MULTIPLY", math(nt, "MULTIPLY", amt, away, x + 1800, y - 1050), math(nt, "MAXIMUM", rim["Rim Intensity"], 0.0, x + 1620, y - 1600), x + 1980, y - 1050)
            own_col = mix_rgb(nt, "MULTIPLY", rim["Rim Use Base"], rim["Rim Color"], base, x + 1440, y - 900, clamp=False)
            own_col = mix_rgb(nt, "MULTIPLY", 1.0, own_col, tint, x + 1800, y - 900, clamp=False)
            own_col = mix_rgb(nt, "MULTIPLY", 1.0, own_col, amt, x + 2160, y - 900, clamp=False)
            col = mix_rgb(nt, "ADD", 1.0, col, own_col, x + 2340, y)
        return col


def shader_out(nt, color, alpha, out_node, x, y):
    em = node(nt, "ShaderNodeEmission", x, y)
    nt.links.new(color, em.inputs["Color"])
    tr = node(nt, "ShaderNodeBsdfTransparent", x, y - 140)
    mx = node(nt, "ShaderNodeMixShader", x + 200, y)
    nt.links.new(alpha, mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out_node.inputs["Shader"])


# ---------- node groups ----------
GROUP_VERSION = 13  # bump when a group changes; 2 = colours and light objects per character (and the outline
#   group's first version mark: older unmarked ST Outline groups, without the no-COL0 fallback, get rebuilt);
#   3 = matcap UV without Vector Transform (broken in Blender 5.3); 6 = panel colours, shadow softness, rim;
#   10 = shadow ramps, specular, hair highlight; 11 = hair shadow on the face;
#   12 = environment reflection, specular from Mask2's B; 13 = Spec1 curve


def shared_group(name, typ, version=None):
    """(group, already_built). Groups are shared by every character, so an up-to-date one is reused:
    rebuilding it would unlink the other characters' materials. An outdated one is renamed, not
    deleted, so the characters already using it keep working."""
    version = version or GROUP_VERSION
    ng = bpy.data.node_groups.get(name)
    if ng and ng.get("st_version") == version:
        return ng, True
    if ng:
        ng.name = f"{name} (v{ng.get('st_version', 1)})"
    ng = bpy.data.node_groups.new(name, typ)
    ng["st_version"] = version
    return ng, False


def matcap_uv(nt, N, x, y):
    """MatCap UV: the normal N seen from the viewer, in 0..1. Built from the view direction (Geometry >
    Incoming) instead of a Vector Transform World -> Camera: in Blender 5.3 that node returns a constant,
    and the whole character took one colour of the matcap (a pink tint from some angles)."""
    geo = node(nt, "ShaderNodeNewGeometry", x, y - 150)
    fwd = node(nt, "ShaderNodeVectorMath", x + 180, y - 150, operation="SCALE")
    nt.links.new(geo.outputs["Incoming"], fwd.inputs[0])
    fwd.inputs["Scale"].default_value = -1.0  # Incoming points at the viewer: the view looks the other way
    side = node(nt, "ShaderNodeVectorMath", x + 360, y - 150, operation="CROSS_PRODUCT")
    nt.links.new(fwd.outputs[0], side.inputs[0])
    side.inputs[1].default_value = (0.0, 0.0, 1.0)
    right = vmath(nt, "NORMALIZE", side.outputs[0], None, x + 540, y - 150)
    up = vmath(nt, "CROSS_PRODUCT", right.outputs[0], fwd.outputs[0], x + 540, y - 300)
    u = vmath(nt, "DOT_PRODUCT", N, right.outputs[0], x + 720, y - 150).outputs["Value"]
    v = vmath(nt, "DOT_PRODUCT", N, up.outputs[0], x + 720, y - 300).outputs["Value"]
    comb = node(nt, "ShaderNodeCombineXYZ", x + 900, y - 200)
    nt.links.new(u, comb.inputs[0])
    nt.links.new(v, comb.inputs[1])
    ma = node(nt, "ShaderNodeVectorMath", x + 1080, y - 200, operation="MULTIPLY_ADD")
    nt.links.new(comb.outputs[0], ma.inputs[0])
    ma.inputs[1].default_value = (0.5, 0.5, 0.5)
    ma.inputs[2].default_value = (0.5, 0.5, 0.0)
    return ma.outputs[0]


def matcap_quadrant(nt, uv, mask, x, y):
    """MatCap UV into one quarter of a 4-matcap atlas (NeedMatCap4text): Mask1's red channel picks it,
    in four steps (0-0.25 top left, then top right, bottom left, bottom right; Unreal reads textures
    from the top). Checked against the game on Eika S211: cloth, skin and satin get their own matcap."""
    sep = node(nt, "ShaderNodeSeparateColor", x, y)
    nt.links.new(mask.outputs["Color"], sep.inputs[0])
    idx = math(nt, "MINIMUM", math(nt, "FLOOR", math(nt, "MULTIPLY", sep.outputs[0], 4.0, x + 180, y), None, x + 360, y), 3.0, x + 540, y)
    col = math(nt, "MODULO", idx, 2.0, x + 720, y)  # 0 left, 1 right
    row = math(nt, "FLOOR", math(nt, "DIVIDE", idx, 2.0, x + 720, y - 150), None, x + 900, y - 150)  # 0 top, 1 bottom
    off = node(nt, "ShaderNodeCombineXYZ", x + 1080, y - 50)
    nt.links.new(math(nt, "MULTIPLY", col, 0.5, x + 900, y), off.inputs[0])
    nt.links.new(math(nt, "SUBTRACT", 0.5, math(nt, "MULTIPLY", row, 0.5, x + 1080, y - 150), x + 1260, y - 150), off.inputs[1])  # V grows up
    half = node(nt, "ShaderNodeVectorMath", x + 1080, y + 150, operation="SCALE")
    nt.links.new(uv, half.inputs[0])
    half.inputs["Scale"].default_value = 0.5
    return vmath(nt, "ADD", half.outputs[0], off.outputs[0], x + 1440, y).outputs[0]


RIM_INPUTS = {  # ST Toon input: (type, default); off unless the material's JSON sets an intensity
    "Rim Color": ("NodeSocketColor", (1, 1, 1, 1)), "Rim Intensity": ("NodeSocketFloat", 0.0),
    "Rim Exponent": ("NodeSocketFloat", 2.0), "Rim Scale": ("NodeSocketFloat", 1.0),
    "Rim Range": ("NodeSocketFloat", 0.5), "Rim Dot Scale": ("NodeSocketFloat", 1.0),
    "Rim Use Base": ("NodeSocketFloat", 0.0),
}
RIM_SCALARS = {"Rim Intensity": "RimLightIntensity", "Rim Exponent": "RimFresnelEXP", "Rim Scale": "RimFresnelScale",
               "Rim Range": "RimRange", "Rim Dot Scale": "RimDotScale"}


def matcap_channel(nt, mc, mask, x, y):
    """A single-channel matcap texture holds four grey matcaps, one per channel (R, G, B, A); Mask1's red
    picks it in four steps, like the quarters of an atlas. Without a mask, the first."""
    sep = node(nt, "ShaderNodeSeparateColor", x, y)
    nt.links.new(mc.outputs["Color"], sep.inputs[0])
    out = sep.outputs[0]
    if mask:
        red = node(nt, "ShaderNodeSeparateColor", x, y - 200)
        nt.links.new(mask.outputs["Color"], red.inputs[0])
        for i, ch in enumerate((sep.outputs[1], sep.outputs[2], mc.outputs["Alpha"]), 1):
            out = mix_rgb(nt, "MIX", math(nt, "GREATER_THAN", red.outputs[0], i / 4 - 0.001, x + 180 * i, y - 200), out, ch, x + 180 * i, y)
    return out


def specular(nt, N, L, V, base, gi, lit, x, y):
    """GGX highlight of the sun plus the environment's reflection: metal tints both with the base colour.
    The highlight's curve (Spec1 of the old materials, read from its parameters' names and values): clipped
    to Spec Range and normalized, from soft (Spec Sharpness 0) to a toon step at Spec Begin (1), times
    Spec Intensity; in the shadow, times Spec Shadow. The defaults leave the plain GGX, up to 5."""
    H = vmath(nt, "NORMALIZE", vmath(nt, "ADD", L, V, x, y).outputs[0], None, x + 180, y).outputs[0]
    nh = math(nt, "MAXIMUM", vmath(nt, "DOT_PRODUCT", N, H, x + 360, y).outputs["Value"], 0.0, x + 540, y)
    a = math(nt, "MAXIMUM", math(nt, "POWER", gi.outputs["Roughness"], 2.0, x, y - 200), 0.04, x + 180, y - 200)
    a2 = math(nt, "MULTIPLY", a, a, x + 360, y - 200)
    d = math(nt, "MULTIPLY_ADD", math(nt, "MULTIPLY", nh, nh, x + 720, y), math(nt, "SUBTRACT", a2, 1.0, x + 540, y - 200), x + 900, y)
    nt.nodes[-1].inputs[2].default_value = 1.0
    # no pi: a lit surface here emits its base colour (a light of intensity pi)
    ggx = math(nt, "DIVIDE", a2, math(nt, "MULTIPLY", math(nt, "MULTIPLY", d, d, x + 1080, y), 4.0, x + 1260, y), x + 1440, y)
    rng = math(nt, "MAXIMUM", gi.outputs["Spec Range"], 0.01, x + 1440, y + 200)
    t = math(nt, "DIVIDE", math(nt, "MINIMUM", ggx, rng, x + 1620, y), rng, x + 1800, y)
    lo = math(nt, "MULTIPLY", gi.outputs["Spec Begin"], gi.outputs["Spec Sharpness"], x + 1440, y + 400)
    hi = math(nt, "SUBTRACT", 1.0, math(nt, "MULTIPLY", math(nt, "SUBTRACT", 1.0, gi.outputs["Spec Begin"], x + 1440, y + 600),
                                        gi.outputs["Spec Sharpness"], x + 1620, y + 600), x + 1800, y + 600)
    width = math(nt, "MAXIMUM", math(nt, "SUBTRACT", hi, lo, x + 1980, y + 500), 0.02, x + 2160, y + 500)
    step = math(nt, "MAXIMUM", math(nt, "DIVIDE", math(nt, "SUBTRACT", t, lo, x + 1980, y + 200), width, x + 2160, y + 200), 0.0, x + 2340, y + 200)
    amt = math(nt, "MULTIPLY", math(nt, "MINIMUM", step, 1.0, x + 2520, y + 200), gi.outputs["Spec Intensity"], x + 2700, y + 200)
    shade = mix_rgb(nt, "MIX", lit, gi.outputs["Spec Shadow"], (1.0, 1.0, 1.0, 1.0), x + 2520, y)
    amt = mix_rgb(nt, "MULTIPLY", 1.0, shade, amt, x + 2880, y + 100, clamp=False)
    f0 = mix_rgb(nt, "MIX", gi.outputs["Metallic"], mix_rgb(nt, "MULTIPLY", 1.0, gi.outputs["Specular"], (0.08, 0.08, 0.08, 1.0), x + 1440, y - 250), base, x + 1620, y - 250)
    direct = mix_rgb(nt, "MULTIPLY", 1.0, f0, amt, x + 2160, y - 100, clamp=False)
    # the environment: a sky / horizon / ground gradient in place of the game's panorama, flatter when rough
    nv = vmath(nt, "DOT_PRODUCT", N, V, x, y - 500).outputs["Value"]
    fres = math(nt, "MULTIPLY", math(nt, "POWER", math(nt, "SUBTRACT", 1.0, math(nt, "ABSOLUTE", nv, None, x + 180, y - 500), x + 360, y - 500), 5.0, x + 540, y - 500),
                gi.outputs["Specular"], x + 720, y - 500)
    inv = node(nt, "ShaderNodeVectorMath", x, y - 700, operation="SCALE")
    nt.links.new(V, inv.inputs[0])
    inv.inputs["Scale"].default_value = -1.0
    refl = node(nt, "ShaderNodeSeparateXYZ", x + 360, y - 700)
    nt.links.new(vmath(nt, "REFLECT", inv.outputs[0], N, x + 180, y - 700).outputs[0], refl.inputs[0])
    sharp = math(nt, "SUBTRACT", 1.0, gi.outputs["Roughness"], x + 360, y - 850)
    up = math(nt, "MULTIPLY_ADD", math(nt, "MULTIPLY", refl.outputs["Z"], sharp, x + 540, y - 700), 0.5, x + 720, y - 700)
    nt.nodes[-1].inputs[2].default_value = 0.5
    sky = node(nt, "ShaderNodeValToRGB", x + 900, y - 700)
    nt.links.new(up, sky.inputs[0])
    els = sky.color_ramp.elements
    while len(els) < len(ENVIRONMENT):
        els.new(1.0)
    for e, (pos, c) in zip(els, ENVIRONMENT):
        e.position, e.color = pos, (*c, 1.0)
    env = mix_rgb(nt, "MULTIPLY", 1.0, sky.outputs[0], mix_rgb(nt, "ADD", 1.0, f0, fres, x + 1800, y - 500, clamp=False), x + 1980, y - 600, clamp=False)
    env = mix_rgb(nt, "MULTIPLY", 1.0, env, gi.outputs["Environment"], x + 2160, y - 600, clamp=False)
    return mix_rgb(nt, "ADD", 1.0, direct, env, x + 2340, y - 300, clamp=False)


SPEC1 = {"Spec Intensity": 5.0, "Spec Range": 5.0, "Spec Begin": 0.0, "Spec Sharpness": 0.0}
OLD_SPEC1 = {"Spec Intensity": ("Spec1_Intensity", 1.0), "Spec Range": ("Spec1_RangeMax", 10.0),  # mat_toon's defaults
             "Spec Begin": ("Spec1_Begin", 0.5), "Spec Sharpness": ("Spec1_Sharpness", 0.0)}
ENVIRONMENT = (  # height of the reflected direction (0 below, 1 above): linear colour
    (0.0, (0.03, 0.02, 0.015)), (0.42, (0.22, 0.17, 0.1)), (0.49, (0.3, 0.26, 0.18)), (0.53, (1.0, 1.0, 1.0)),
    (0.65, (0.35, 0.5, 0.8)), (1.0, (0.12, 0.2, 0.38)))


def build_toon_group():
    ng, built = shared_group("ST Toon", "ShaderNodeTree")
    if built:
        return ng
    sock(ng, "Shader", "OUTPUT", "NodeSocketShader")
    sock(ng, "MatCap UV", "OUTPUT", "NodeSocketVector")
    sock(ng, "Base Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    sock(ng, "Alpha", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Normal", "INPUT", "NodeSocketVector").hide_value = True  # always linked by setup_material
    sock(ng, "Ramp ID", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Middle Value", "INPUT", "NodeSocketFloat", 0.15)
    sock(ng, "Softness", "INPUT", "NodeSocketFloat", 0.03)
    sock(ng, "MatCap", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    sock(ng, "MatCap Pow", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "Emission", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    sock(ng, "Metallic", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "Roughness", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Specular", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "Environment", "INPUT", "NodeSocketFloat", 0.0)
    for name, default in SPEC1.items():
        sock(ng, name, "INPUT", "NodeSocketFloat", default)
    sock(ng, "Spec Shadow", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    sock(ng, "Highlight", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "View Limit", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "View Limit Blur", "INPUT", "NodeSocketFloat", 0.1)
    for name, (typ, default) in RIM_INPUTS.items():
        sock(ng, name, "INPUT", typ, default)
    nt = ng
    with section(nt, "Inputs", "in"):
        gi = node(nt, "NodeGroupInput", -900, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    with section(nt, "Light: N.L with the sun direction (lit side)", "light"):
        L = attr(nt, "lightDir", -700, 300)
        N = vmath(nt, "NORMALIZE", gi.outputs["Normal"], None, -700, 100).outputs[0]
        ndl = vmath(nt, "DOT_PRODUCT", N, L, -400, 200).outputs["Value"]
        lit = soft_step(nt, ndl, gi.outputs["Middle Value"], scaled_softness(nt, gi.outputs["Softness"], -700, -50), -200, 200)
        soft = math(nt, "MULTIPLY_ADD", ndl, 0.5, 0, 0)
        nt.nodes[-1].inputs[2].default_value = 0.5
        # half Lambert with the ramp's middle at N.L = Middle Value (-99, eyes and brows: always lit)
        u = math(nt, "MULTIPLY_ADD", math(nt, "SUBTRACT", ndl, gi.outputs["Middle Value"], 0, -200), 0.5, 180, -200)
        nt.nodes[-1].inputs[2].default_value = 0.5
        ramp = ramp_color(nt, u, gi.outputs["Ramp ID"], scaled_softness(nt, 1.0, -700, -400), 360, -200)
    with section(nt, "MatCap UV (camera-space normal)", "tex"):
        nt.links.new(matcap_uv(nt, N, -500, -250), go.inputs["MatCap UV"])
    col = toon_mix(nt, lit, soft, ndl, N, gi.outputs["Base Color"], None,
                   {k: gi.outputs[k] for k in RIM_INPUTS}, 100, 100, ramp)
    with section(nt, "MatCap and emission", "color"):
        col = mix_rgb(nt, "ADD", gi.outputs["MatCap Pow"], col, gi.outputs["MatCap"], 450, 100)
        col = mix_rgb(nt, "ADD", 1.0, col, gi.outputs["Emission"], 600, 100)
    with section(nt, "Specular and hair highlight", "light"):
        view = node(nt, "ShaderNodeNewGeometry", 0, -900).outputs["Incoming"]
        col = mix_rgb(nt, "ADD", 1.0, col, specular(nt, N, L, view, gi.outputs["Base Color"], gi, lit, 200, -900), 2600, -700)
        # the hair's painted highlight, only where it faces the viewer: ViewLimit 1 (the default) = everywhere
        nv = vmath(nt, "DOT_PRODUCT", N, view, 200, -1400).outputs["Value"]
        facing = soft_step(nt, nv, math(nt, "SUBTRACT", 1.0, gi.outputs["View Limit"], 200, -1550), gi.outputs["View Limit Blur"], 400, -1400)
        col = mix_rgb(nt, "ADD", 1.0, col, math(nt, "MULTIPLY", facing, gi.outputs["Highlight"], 900, -1400), 2800, -700)
    with section(nt, "Output (emission + transparency)", "out", extra=(go,)):
        shader_out(nt, col, gi.outputs["Alpha"], go, 650, -150)
    arrange_sections(nt)
    return ng


def hair_shadow(nt, L, bias, x, y):
    """1 where the hair in front of the face blocks the sun. Like the game's (HairShadowBias), what is less
    than `bias` metres nearer to the viewer than the skin casts nothing: the nose, the lids, the lashes.
    The ray is short: a fringe's narrow shadow, not the one of a hat's brim.
    shortcut: EEVEE traces the screen, so hair out of the frame casts nothing and the edge is a bit noisy."""
    geo = node(nt, "ShaderNodeNewGeometry", x, y)
    off = node(nt, "ShaderNodeVectorMath", x + 180, y, operation="SCALE")
    nt.links.new(geo.outputs["Incoming"], off.inputs[0])
    nt.links.new(bias, off.inputs["Scale"])
    ray = node(nt, "ShaderNodeRaycast", x + 540, y)
    nt.links.new(vmath(nt, "ADD", geo.outputs["Position"], off.outputs[0], x + 360, y).outputs[0], ray.inputs["Position"])
    nt.links.new(L, ray.inputs["Direction"])
    ray.inputs["Length"].default_value = 0.04
    return ray.outputs["Is Hit"]


def build_face_group():
    ng, built = shared_group("ST Face", "ShaderNodeTree")
    if built:
        return ng
    sock(ng, "Shader", "OUTPUT", "NodeSocketShader")
    sock(ng, "SDF UV", "OUTPUT", "NodeSocketVector")
    sock(ng, "Base Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    sock(ng, "Alpha", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "SDF", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Ramp ID", "INPUT", "NodeSocketFloat", 4.0)
    sock(ng, "Softness", "INPUT", "NodeSocketFloat", 0.01)
    sock(ng, "Hair Shadow", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "Hair Shadow Bias", "INPUT", "NodeSocketFloat", 0.015)
    sock(ng, "Flip Side", "INPUT", "NodeSocketFloat", 0.0)  # set 1 if shadow lands on the wrong side
    nt = ng
    with section(nt, "Inputs", "in"):
        gi = node(nt, "NodeGroupInput", -1300, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    with section(nt, "Vectors: light and head orientation", "light"):
        L = attr(nt, "lightDir", -1100, 400)
        F = attr(nt, "headForward", -1100, 250)
        U = attr(nt, "headUp", -1100, 100)
    with section(nt, "Light projected on the head plane (front / side)", "light"):
        lu = vmath(nt, "DOT_PRODUCT", L, U, -800, 400).outputs["Value"]
        su = node(nt, "ShaderNodeVectorMath", -650, 400, operation="SCALE")
        nt.links.new(U, su.inputs[0])
        nt.links.new(lu, su.inputs["Scale"])
        lp = vmath(nt, "SUBTRACT", L, su.outputs[0], -500, 400).outputs[0]
        lp = vmath(nt, "NORMALIZE", lp, None, -350, 400).outputs[0]
        f = vmath(nt, "DOT_PRODUCT", F, lp, -200, 400).outputs["Value"]
        right = vmath(nt, "CROSS_PRODUCT", F, U, -500, 200).outputs[0]
        r = vmath(nt, "DOT_PRODUCT", right, lp, -200, 200).outputs["Value"]
    with section(nt, "SDF UV: mirrored by the light side", "tex"):
        side = math(nt, "GREATER_THAN", r, 0.0, 0, 200)
        side = math(nt, "ABSOLUTE", math(nt, "SUBTRACT", side, gi.outputs["Flip Side"], 150, 250), None, 300, 250)
        uv = node(nt, "ShaderNodeUVMap", -500, -100)
        sep = node(nt, "ShaderNodeSeparateXYZ", -300, -100)
        nt.links.new(uv.outputs[0], sep.inputs[0])
        u = sep.outputs["X"]
        one_minus_2u = math(nt, "MULTIPLY_ADD", u, -2.0, 0, -100)
        nt.nodes[-1].inputs[2].default_value = 1.0
        u2 = math(nt, "MULTIPLY_ADD", side, one_minus_2u, 450, -50)
        nt.links.new(u, nt.nodes[-1].inputs[2])
        comb = node(nt, "ShaderNodeCombineXYZ", 650, -100)
        nt.links.new(u2, comb.inputs["X"])
        nt.links.new(sep.outputs["Y"], comb.inputs["Y"])
        nt.links.new(comb.outputs[0], go.inputs["SDF UV"])
    with section(nt, "Face shadow: SDF threshold (0 = light in front, 1 = behind)", "light"):
        thr = math(nt, "MULTIPLY_ADD", f, -0.5, 0, 450)
        nt.nodes[-1].inputs[2].default_value = 0.5
        lit = soft_step(nt, gi.outputs["SDF"], thr, scaled_softness(nt, gi.outputs["Softness"], -200, 250), 200, 450)
        soft = soft_step(nt, gi.outputs["SDF"], thr, 0.5, 200, 250)
        normal = node(nt, "ShaderNodeNewGeometry", 0, 100).outputs["Normal"]
        u = math(nt, "MULTIPLY_ADD", math(nt, "SUBTRACT", gi.outputs["SDF"], thr, 200, 50), 3.0, 380, 50)
        nt.nodes[-1].inputs[2].default_value = RAMP_EDGE
        amount = math(nt, "MULTIPLY", gi.outputs["Hair Shadow"], packed(nt, "st_l_ambient", -200, -450)[1], 0, -450)
        free = math(nt, "SUBTRACT", 1.0, math(nt, "MULTIPLY", hair_shadow(nt, L, gi.outputs["Hair Shadow Bias"], -600, -650), amount, 200, -450), 380, -450)
        lit = math(nt, "MULTIPLY", lit, free, 560, 450)
        u = math(nt, "MINIMUM", u, free, 740, 50)
        ramp = ramp_color(nt, u, gi.outputs["Ramp ID"], scaled_softness(nt, 1.0, -200, -300), 560, 50)
    col = toon_mix(nt, lit, soft, None, normal, gi.outputs["Base Color"], None, None, 400, 150, ramp)
    with section(nt, "Output (emission + transparency)", "out", extra=(go,)):
        shader_out(nt, col, gi.outputs["Alpha"], go, 650, -300)
    arrange_sections(nt)
    return ng


VECTOR_INPUTS = ("Sun", "Head", "Head Forward", "Head Up")  # set on each character's modifier


def build_vectors_gn():
    ng, built = shared_group("ST Light Vectors", "GeometryNodeTree")
    if built:
        return ng
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    for n in VECTOR_INPUTS:
        sock(ng, n, "INPUT", "NodeSocketObject")
    nt = ng
    with section(nt, "Input", "in"):
        gi = node(nt, "NodeGroupInput", -800, 0)
    go = node(nt, "NodeGroupOutput", 800, 0)

    def info(name, y):
        n = node(nt, "GeometryNodeObjectInfo", -550, y, transform_space="ORIGINAL")
        nt.links.new(gi.outputs[name], n.inputs["Object"])
        return n

    with section(nt, "Objects: sun and head empties (set by the modifier)", "light"):
        li, ho, hf, hu = (info(n, y) for n, y in zip(VECTOR_INPUTS, (300, 0, -250, -500)))
    with section(nt, "Vectors: light direction, head forward and up", "light"):
        rot = node(nt, "FunctionNodeRotateVector", -300, 300)
        rot.inputs["Vector"].default_value = (0, 0, 1)  # sun shines along its -Z, so +Z points toward the light
        nt.links.new(li.outputs["Rotation"], rot.inputs["Rotation"])
        fwd = vmath(nt, "SUBTRACT", hf.outputs["Location"], ho.outputs["Location"], -300, -100)
        up = vmath(nt, "SUBTRACT", hu.outputs["Location"], ho.outputs["Location"], -300, -350)
    with section(nt, "Store as attributes (read by the shader)", "out", extra=(go,)):
        geo = gi.outputs["Geometry"]
        for i, (name, val) in enumerate((("lightDir", rot.outputs[0]), ("headForward", fwd.outputs[0]), ("headUp", up.outputs[0]))):
            st = node(nt, "GeometryNodeStoreNamedAttribute", 0 + i * 220, 0, data_type="FLOAT_VECTOR", domain="POINT")
            st.inputs["Name"].default_value = name
            nt.links.new(geo, st.inputs["Geometry"])
            nt.links.new(val, st.inputs["Value"])
            geo = st.outputs["Geometry"]
        nt.links.new(geo, go.inputs["Geometry"])
    arrange_sections(nt)
    return ng


# ---------- per-character sun + head empties ----------
# Each character owns its sun, head empties and lighting panel (ID pointers in its mesh's custom
# properties, so renames don't break them): two characters can be lit differently.
def own(obj, key, make):
    """Object stored in obj[key]; made and stored if missing or deleted."""
    ob = obj.get(key)
    if not isinstance(ob, bpy.types.Object):
        ob = obj[key] = make()
    return ob


def ensure_rig(obj, arm):
    # raw FModel skeleton, or the Rigify rig made by "Generar rig"
    head_bone = _head_bone(arm) or "Bip001-Head"
    col = obj.users_collection[0]

    def new_sun():
        sun = bpy.data.objects.new(f"ST_Light {obj.name}", bpy.data.lights.new(f"ST_Light {obj.name}", "SUN"))
        sun.rotation_euler = (0.9, 0.0, -0.5)  # front, above, slightly to the side
        return sun

    sun = own(obj, "st_light", new_sun)
    if not sun.users_collection:
        col.objects.link(sun)
    head = arm.matrix_world @ arm.pose.bones[head_bone].head
    empties = {}
    for name, off in (("Origin", (0, 0, 0)), ("Forward", (0, -0.1, 0)), ("Up", (0, 0, 0.1))):  # model faces -Y
        e = own(obj, f"st_head_{name.lower()}", lambda: bpy.data.objects.new(f"ST_Head{name} {obj.name}", None))
        if not e.users_collection:
            col.objects.link(e)
        e.empty_display_size = 0.02
        e.parent, e.parent_type, e.parent_bone = arm, "BONE", head_bone
        bpy.context.view_layer.update()
        mw = e.matrix_world.copy()
        mw.translation = head + mathutils.Vector(off)
        e.matrix_world = mw
        # inputs of the ST Light Vectors modifier, nothing to grab: disabled in viewport (survives
        # Alt+H). Tested: the modifier still reads them as the head moves; re-enable in the Outliner.
        e.hide_viewport = True
        empties[name] = e
    return sun, empties


# ---------- sidebar lighting settings ----------
# Set on each character's 3D mesh (animatable); drivers copy them, or the rig's wheels, to the object
# properties the shader reads (st_l_<colour>). EEVEE gives a material at most 8 object attributes, so
# the scalars travel in the colours' alpha.
LIGHTING_TYPE = "st_lighting_type"
COLORS = ("ambient", "sharp_lit", "soft_lit", "sharp_shadow", "soft_shadow", "rim_lit", "rim_shadow")
SCALARS = {  # property: (default, min, max, description)
    "st_rim_scale": (1.0, 0.0, 5.0, "Strength of the rim light"),
    "st_rim_extra": (0.0, 0.0, 1.0, "Rim light for every material, also those whose game data has none"),
    "st_hair_shadow": (1.0, 0.0, 1.0, "Shadow the hair casts on the face"),
    "st_shadow_softness": (1.0, 0.0, 20.0, "Edge between light and shadow: 0 hard, higher softer (1 = default)"),
}
ALPHA = {"ambient": "st_hair_shadow", "sharp_lit": LIGHTING_TYPE, "sharp_shadow": "st_shadow_softness", "soft_lit": "st_rim_extra", "rim_lit": "st_rim_scale"}
ALPHA_NEUTRAL = {"sharp_lit": 0.0, "soft_lit": 0.0}  # the others 1
LEGACY_PICKS = {"sharp_lit": "st_light_pick", "sharp_shadow": "st_ambient_pick"}  # characters imported up to 1.2
LEGACY_BONES = {"Sharp Lit": "ST Light", "Sharp Shadow": "ST Ambient"}


def ui_name(color):
    return color.replace("_", " ").title()


def ensure_settings(mesh):
    """The sidebar's lighting properties on a character mesh (kept if it already has them). Texts in
    English: Blender translates them when it shows them, so they follow a change of language."""
    if LIGHTING_TYPE not in mesh:
        mesh[LIGHTING_TYPE] = 0
        mesh.id_properties_ui(LIGHTING_TYPE).update(min=0, max=1, items=[
            ("RIG", "Rig Panel", "Colours and intensities from the wheels next to the character", 0, 0),
            ("PARAMETERS", "Parameter Panel", "Colours from this panel; the rig's wheels are hidden", 0, 1)])
    for c in COLORS:
        if f"st_{c}" not in mesh:
            mesh[f"st_{c}"] = (1.0, 1.0, 1.0)
            mesh.id_properties_ui(f"st_{c}").update(subtype="COLOR", min=0.0, max=1.0, default=(1.0, 1.0, 1.0))
    for p, (default, lo, hi, text) in SCALARS.items():
        if p not in mesh:
            mesh[p] = default
            mesh.id_properties_ui(p).update(min=lo, max=hi, default=default, description=text)


def _drive(owner, path, index, expr, variables):
    """Scripted driver on owner[path] (index -1: not an array). variables: (name, id, data path), or
    (name, id, bone, channel) for a pose bone's local location."""
    args = (path,) if index < 0 else (path, index)
    owner.driver_remove(*args)
    if not expr:
        return
    d = owner.driver_add(*args).driver
    d.type = "SCRIPTED"
    for name, target, where, *channel in variables:
        v = d.variables.new()
        v.name, v.type = name, "TRANSFORMS" if channel else "SINGLE_PROP"
        t = v.targets[0]
        t.id = target
        if channel:
            t.bone_target, t.transform_type, t.transform_space = where, channel[0], "LOCAL_SPACE"
        else:
            t.data_path = where
    d.expression = expr  # simple expressions: no auto-run needed


def _neutral(mesh, color):
    mesh[f"st_l_{color}"] = (0.0, 0.0, 1.0, ALPHA_NEUTRAL.get(color, 1.0))  # a centred wheel: white


def bind_settings(mesh, arm):
    """Drive a character mesh's st_l_* properties from its sidebar settings or, with the Rig Panel, from
    the pickers in `arm`."""
    ensure_settings(mesh)
    mesh.update_tag()  # the evaluated object must get the new properties, or the drivers go invalid
    mode = ("m", mesh, f'["{LIGHTING_TYPE}"]')
    for c in COLORS:
        _neutral(mesh, c)
        bone = picker_bone(arm, ui_name(c))
        for i, (b, ch) in enumerate(((bone, "LOC_X"), (bone, "LOC_Z"), (f"{bone} Value", "LOC_Z"))):
            wheel = f"p / {R}" if bone else ("1.0" if i == 2 else "0.0")  # an older rig lacks some wheels: white
            _drive(mesh, f'["st_l_{c}"]', i, f"c if m else {wheel}",
                   [mode, ("c", mesh, f'["st_{c}"][{i}]')] + ([("p", arm, b, ch)] if bone else []))
        if c in ALPHA:
            _drive(mesh, f'["st_l_{c}"]', 3, "v", [("v", mesh, f'["{ALPHA[c]}"]')])


def follow_settings(mesh, host):
    """Light `mesh` (a paper version, a weapon) with `host`'s panel; neutral without one."""
    for c in COLORS:
        name = f"st_l_{c}"
        _neutral(mesh, c)
        old = LEGACY_PICKS.get(c)
        src = host and next((p for p in (name, old) if p and p in host), None)
        for i in range(4):
            _drive(mesh, f'["{name}"]', i, "v" if src and (i < 3 or src == name) else "", [("v", host, f'["{src}"][{i}]')])
        if old and old in mesh:  # a weapon imported up to 1.2, whose shader reads the wheels from here
            mesh[old] = (0.0, 0.0, 1.0)
            for i in range(3):
                src = host and next((p for p in (old, name) if p in host), None)
                _drive(mesh, f'["{old}"]', i, "v" if src else "", [("v", host, f'["{src}"][{i}]')])


def lighting_source(mesh):
    """The mesh whose settings light `mesh`: a paper version's or a held weapon's character, a loose
    weapon's main mesh, or itself. None for a mesh shaded before these settings existed."""
    if mesh and (mesh.get("st_weapon") or mesh.get("st_light_host")):
        mesh = mesh.get("st_weapon_host") or mesh.get("st_weapon_lead") or mesh.get("st_light_host")
    return mesh if isinstance(mesh, bpy.types.Object) and LIGHTING_TYPE in mesh else None


# ---------- materials ----------
def load_img(path, colorspace):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def tex(nt, path, colorspace, x, y, vector=None):
    n = node(nt, "ShaderNodeTexImage", x, y, image=load_img(path, colorspace))
    if vector is not None:
        nt.links.new(vector, n.inputs["Vector"])
    return n


def normal_nodes(nt, path, groups):
    """Normal map from `path` (or the geometry's normal without one) into the Normal input of each
    group node. Returns (nodes, frame label)."""
    if not path:
        geo = node(nt, "ShaderNodeNewGeometry", -60, -150)
        for g in groups:
            nt.links.new(geo.outputs["Normal"], g.inputs["Normal"])
        return [geo], "Geometry normal (no normal map)"
    n_img = tex(nt, path, "Non-Color", -800, -150)
    # UE normal maps are DirectX style: flip green for Blender
    sep = node(nt, "ShaderNodeSeparateColor", -550, -150)
    inv = node(nt, "ShaderNodeMath", -380, -150, operation="SUBTRACT")
    inv.inputs[0].default_value = 1.0
    comb = node(nt, "ShaderNodeCombineColor", -220, -150)
    nm = node(nt, "ShaderNodeNormalMap", -60, -150, uv_map="UV0")
    nt.links.new(n_img.outputs["Color"], sep.inputs[0])
    nt.links.new(sep.outputs[0], comb.inputs[0])
    nt.links.new(sep.outputs[1], inv.inputs[1])
    nt.links.new(inv.outputs[0], comb.inputs[1])
    nt.links.new(sep.outputs[2], comb.inputs[2])
    nt.links.new(comb.outputs[0], nm.inputs["Color"])
    for g in groups:
        nt.links.new(nm.outputs[0], g.inputs["Normal"])
    return [n_img, sep, inv, comb, nm], "Normal map (DirectX to Blender: green channel flipped)"


def setup_material(mat, data, tex_idx, mesh_skin, face_group, toon_group, report):
    skin = skin_of(mat.name, mesh_skin)
    t = {k: v["ObjectName"].split("'")[1] for k, v in data.get("Textures", {}).items() if v}  # FModel writes null for unresolved textures
    sca, cols, sw = data.get("Scalars", {}), data.get("Colors", {}), data.get("Switches", {})
    props = data.get("Properties", {}).get("BasePropertyOverrides", {})
    base_p = pick(tex_idx, t.get("BaseMap", ""), skin)
    if not base_p:
        # a translucent colour layer with no texture: the shadow the eyelid casts on the eye
        # (MI_Toon_EyeShadow, dark grey at 45%)
        if cols.get("BaseColor") and props.get("BlendMode") == "BLEND_Translucent":
            glass_material(mat, cols["BaseColor"], sca.get("Opacity", 0.5), report)
        elif t.get("BaseMap"):
            report[mat.name] = MISSING + t["BaseMap"]
        else:
            report[mat.name] = "sin BaseMap, se deja igual"
        return
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    base = tex(nt, base_p, "sRGB", -600, 200)
    is_face = "FaceShadowMask" in t
    g = node(nt, "ShaderNodeGroup", 200, 0, node_tree=face_group if is_face else toon_group)
    nt.links.new(base.outputs["Color"], g.inputs["Base Color"])
    # Paper (Mesh2D) atlases use alpha as the white paper-border mask (0 on the drawing), not as
    # opacity: channel-packed so the colour isn't premultiplied to black, and alpha left unlinked
    paper = f"{os.sep}Mesh2D{os.sep}" in base_p
    if paper:
        base.image.alpha_mode = "CHANNEL_PACKED"
    else:
        nt.links.new(base.outputs["Alpha"], g.inputs["Alpha"])
    nt.links.new(g.outputs["Shader"], out.inputs["Surface"])
    # second instance only provides the SDF/MatCap UV, so the texture -> group link is not a cycle
    g_uv = node(nt, "ShaderNodeGroup", -500, -350, node_tree=g.node_tree, label="UV only")
    used = [os.path.basename(base_p)]
    normal, normal_label, extra_tex = [], "Normal", []  # nodes to frame at the end
    # the ramp: one for the material, or per pixel in Mask1's red, in steps of 0.1 (decoded from 287
    # masks: faces 4, hair 10, skin 4 / 5 / 7; 0.06 = slack for the texture compression)
    mask, mask_p = None, pick(tex_idx, t.get("Mask1", ""), skin)

    def mask1():
        nonlocal mask
        if not mask:
            mask = tex(nt, mask_p, "Non-Color", -900, -700)
            mask.image.alpha_mode = "CHANNEL_PACKED"  # A is data: not to be multiplied into the colour
            mask.interpolation = "Closest"  # its steps are indices: no blending across them
            used.append(os.path.basename(mask_p))
        return mask

    if sw.get("RampIDFromTex") and mask_p:
        red = node(nt, "ShaderNodeSeparateColor", -600, -1100)
        nt.links.new(mask1().outputs["Color"], red.inputs[0])
        ramp_id = math(nt, "MULTIPLY_ADD", red.outputs[0], 10.0, -400, -1100)
        nt.nodes[-1].inputs[2].default_value = 0.06
        nt.links.new(math(nt, "FLOOR", ramp_id, None, -200, -1100), g.inputs["Ramp ID"])
    else:
        g.inputs["Ramp ID"].default_value = max(0.0, min(26.0, sca.get("RampID", 1.0)))
    if is_face:
        if not paper:
            g.inputs["Hair Shadow"].default_value = 1.0
            # 0.7 cm over the game's: below it the lids shade the whites of the eyes here
            g.inputs["Hair Shadow Bias"].default_value = 0.007 + 0.01 * max(0.0, sca.get("HairShadowBias", 0.8))
        sdf_p = pick(tex_idx, t["FaceShadowMask"], skin)
        if sdf_p:
            sdf = tex(nt, sdf_p, "Non-Color", -200, -250, g_uv.outputs["SDF UV"])
            nt.links.new(sdf.outputs["Color"], g.inputs["SDF"])
            used.append(os.path.basename(sdf_p))
            extra_tex = [("SDF de la cara (sombra suave)", sdf)]
    else:
        g.inputs["Middle Value"].default_value = sca.get("MiddleValue", 0.15)  # -99 (eyes, brows): always lit
        for name, key in RIM_SCALARS.items():
            if key in sca:
                g.inputs[name].default_value = sca[key]
        c = cols.get("RimLightColor")
        if c:
            g.inputs["Rim Color"].default_value = (c["R"], c["G"], c["B"], 1)
        g.inputs["Rim Use Base"].default_value = float(bool(sw.get("RimLightUseBaseColor")))
        nrm_p = pick(tex_idx, t.get("NormalMap", ""), skin) if sw.get("NeedNormalMap") else None
        normal, normal_label = normal_nodes(nt, nrm_p, (g, g_uv))
        if nrm_p:
            used.append(os.path.basename(nrm_p))
        mc_p = pick(tex_idx, t.get("MatCapTexture", ""), skin) if sw.get("NeedMatCap") else None
        # a 4-matcap atlas needs Mask1 to pick each pixel's quarter; without it the whole atlas would
        # tint the character, so no matcap
        atlas = sw.get("NeedMatCap4text")
        mc_mask = mask_p and (atlas or sw.get("NeedMask1"))
        if mc_p and (mc_mask or not atlas):
            uv = g_uv.outputs["MatCap UV"]
            power = sca.get("MatCapPow", 0.0)
            if mc_mask and atlas:
                uv = matcap_quadrant(nt, uv, mask1(), -700, -700)
            single = sw.get("UseMatCapSingleChanel")
            mc = tex(nt, mc_p, "Non-Color" if single else "sRGB", -200, -450, uv)
            nt.links.new(matcap_channel(nt, mc, mask1() if mc_mask else None, 100, -700) if single else mc.outputs["Color"], g.inputs["MatCap"])
            g.inputs["MatCap Pow"].default_value = power
            if mc_mask:  # G: where the matcap goes, A: how much. Checked on Eika S211: without it the blacks wash out
                where = node(nt, "ShaderNodeSeparateColor", -600, -900)
                nt.links.new(mask1().outputs["Color"], where.inputs[0])
                amount = math(nt, "MULTIPLY", where.outputs[1], mask.outputs["Alpha"], -400, -900)
                nt.links.new(math(nt, "MULTIPLY", amount, power, -200, -900), g.inputs["MatCap Pow"])
            used.append(os.path.basename(mc_p))
            extra_tex = [("MatCap (brillo / reflejo)", mc)]
        # EmissiveColor is masked by Mask1's blue (flames, gems, painted hair highlights of the newer skins).
        # Without a mask it is a leftover default in many materials (it would white out e.g. Chiyo S105),
        # used only behind the EnableEmissive static switch.
        e = cols.get("EmissiveColor")
        e = e and (max(e["R"], 0.0), max(e["G"], 0.0), max(e["B"], 0.0), 1.0)
        if e and any(e[:3]) and mask_p:
            blue = node(nt, "ShaderNodeSeparateColor", -600, -1300)
            nt.links.new(mask1().outputs["Color"], blue.inputs[0])
            nt.links.new(mix_rgb(nt, "MULTIPLY", 1.0, e, blue.outputs[2], -400, -1300, clamp=False), g.inputs["Emission"])
        elif e and sw.get("EnableEmissive"):
            g.inputs["Emission"].default_value = e
        # the old materials paint the hair highlight in Mask1's red (elsewhere an index)
        power = sca.get("HightLightPow", 0.0)
        if power > 0 and mask_p and not (sw.get("RampIDFromTex") or atlas or sw.get("UseMatCapSingleChanel")):
            red = node(nt, "ShaderNodeSeparateColor", -600, -1500)
            nt.links.new(mask1().outputs["Color"], red.inputs[0])
            # the painted highlights are white: a flat lower value (Kanami S113's 0.61) is a ramp index
            white = soft_step(nt, red.outputs[0], 0.85, 0.15, -400, -1500)
            nt.links.new(math(nt, "MULTIPLY", white, power, 0, -1500), g.inputs["Highlight"])
            g.inputs["View Limit"].default_value = sca.get("ViewLimit", 1.0)
            g.inputs["View Limit Blur"].default_value = max(0.001, sca.get("ViewLimitBlur", 0.1))
        # metal / roughness / strength
        mix_p = pick(tex_idx, t.get("MixTex", ""), skin) if sw.get("UseMetallicTex") or sw.get("UseRoughnessTex") else None
        m2_p = pick(tex_idx, t.get("Mask2", ""), skin) if sw.get("PBR") and sw.get("NeedMask2") else None
        env = sca.get("IBLBrightness", 0.2)
        fixed = cols.get("Mask2(0-1)") if sw.get("PBR") and not m2_p else None
        if fixed:
            for name, ch in (("Metallic", "R"), ("Roughness", "G"), ("Specular", "B")):
                g.inputs[name].default_value = max(0.0, min(1.0, fixed[ch]))
            g.inputs["Environment"].default_value = max(0.0, fixed["A"]) * env
        elif m2_p or mix_p:
            pbr = tex(nt, m2_p or mix_p, "Non-Color", -900, -1700)
            used.append(os.path.basename(m2_p or mix_p))
            sep = node(nt, "ShaderNodeSeparateColor", -600, -1700)
            nt.links.new(pbr.outputs["Color"], sep.inputs[0])
            for name, ch, use in (("Metallic", 0 if m2_p else 1, "UseMetallicTex"), ("Roughness", 1 if m2_p else 0, "UseRoughnessTex")):
                if m2_p or sw.get(use):
                    nt.links.new(sep.outputs[ch], g.inputs[name])
                else:
                    g.inputs[name].default_value = max(0.0, min(1.0, sca.get(name, 0.5)))
            if m2_p:
                pbr.image.alpha_mode = "CHANNEL_PACKED"
                nt.links.new(sep.outputs[2], g.inputs["Specular"])
                nt.links.new(math(nt, "MULTIPLY", pbr.outputs["Alpha"], env, -400, -1800), g.inputs["Environment"])
            else:
                nt.links.new(math(nt, "MULTIPLY", sep.outputs[2], 0.5, -400, -1800), g.inputs["Specular"])  # white = 4%, any non-metal's
                for name, (key, default) in OLD_SPEC1.items():
                    g.inputs[name].default_value = max(0.0, sca.get(key, default))
                c = cols.get("Spec1_ShadowColor") or {"R": 0.5, "G": 0.5, "B": 0.5}
                g.inputs["Spec Shadow"].default_value = (c["R"], c["G"], c["B"], 1.0)
                g.inputs["Environment"].default_value = max(0.0, sca.get("EnvScale", 0.1))
    # sections in data-flow order: textures -> computed UVs -> UV-driven textures -> shading -> output
    frame(nt, "Base texture (colour + alpha)", "tex", [base])
    frame(nt, normal_label, "tex", normal)
    frame(nt, "Computed UVs (SDF / MatCap)", "light", [g_uv])
    for label, n in extra_tex:
        frame(nt, label, "tex", [n])
    frame(nt, "Toon shading" + (" for the face (ST Face)" if is_face else " (ST Toon)"), "color", [g])
    frame(nt, "Output", "out", [out])
    arrange_sections(nt)
    translucent = props.get("BlendMode") == "BLEND_Translucent"
    mat.surface_render_method = "BLENDED" if translucent else "DITHERED"
    mat.use_backface_culling = not props.get("TwoSided", False)
    report[mat.name] = {"tipo": "papel" if paper else "face" if is_face else "toon", "texturas": used}


# ---------- lighting panel in the rig (HSV wheels in the viewport, like Gacha Setup's Genshin panel) ----------
PANEL = "ST Lighting Panel"  # standalone armature until the character gets a rig, then joined into it
PICKERS = {  # colour: (x, z) of its wheel (m): lit colours on the left, their shadow ones on the right
    "Ambient": (0.0, 0.0), "Sharp Lit": (0.0, -0.27), "Sharp Shadow": (0.30, -0.27), "Soft Lit": (0.0, -0.54),
    "Soft Shadow": (0.30, -0.54), "Rim Lit": (0.0, -0.81), "Rim Shadow": (0.30, -0.81)}
R = 0.08  # wheel radius in metres; drivers divide by it so the shader works with a unit wheel
VALUE_MAX = 1.5  # value slider range (1 = texture colour, >1 overexposes)
SLIDER_DX = 0.14
SUN_DIST = 0.8  # default distance of the sun handle from the head
COLL = "Lighting"


def _mesh_obj(name, verts, faces, parent, loc, mat=None, edges=None):
    # panel parts (with a parent) are new for each panel; parentless widgets are shared by name
    me = (None if parent else bpy.data.meshes.get(name)) or bpy.data.meshes.new(name)
    me.clear_geometry()
    if edges is None:
        edges = [] if faces else [(i, (i + 1) % len(verts)) for i in range(len(verts))]
    me.from_pydata(verts, edges, faces or [])
    if mat and not me.materials:
        me.materials.append(mat)
    ob = (None if parent else bpy.data.objects.get(name)) or bpy.data.objects.new(name, me)
    if parent:
        ob.parent, ob.location = parent, loc
        ob.hide_select = ob.hide_render = True  # viewport-only UI
    return ob


def _circle(r, n=48):
    return [(r * cos(tau * i / n), 0.0, r * sin(tau * i / n)) for i in range(n)]


def _emission_mat(name, build):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    tc = node(nt, "ShaderNodeTexCoord", -900, 0)
    sep = node(nt, "ShaderNodeSeparateXYZ", -700, 0)
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    em = node(nt, "ShaderNodeEmission", 400, 0)
    nt.links.new(build(nt, sep), em.inputs["Color"])
    nt.links.new(em.outputs[0], node(nt, "ShaderNodeOutputMaterial", 600, 0).inputs["Surface"])
    return m


def _wheel_colour(nt, sep):
    one = node(nt, "ShaderNodeValue", -500, -300)
    one.outputs[0].default_value = 1.0
    x = math(nt, "DIVIDE", sep.outputs["X"], R, -600, 100)
    z = math(nt, "DIVIDE", sep.outputs["Z"], R, -600, -100)
    return hsv_wheel(nt, x, z, one.outputs[0], -500, 0)


def _ramp_colour(nt, sep):
    v = math(nt, "DIVIDE", sep.outputs["Z"], VALUE_MAX * R, -500, 0)
    cc = node(nt, "ShaderNodeCombineColor", -300, 0)
    for i in range(3):
        nt.links.new(v, cc.inputs[i])
    return cc.outputs[0]


def _reparent(context, ob, parent, bone=None):
    """Change parent keeping the world transform."""
    mw = ob.matrix_world.copy()
    ob.parent = parent
    ob.parent_type = "BONE" if bone else "OBJECT"
    ob.parent_bone = bone or ""
    context.view_layer.update()
    ob.matrix_world = mw


def _head_bone(arm):
    return next((b for b in ("DEF-spine.006", "Bip001-Head") if b in arm.data.bones), None)


def create_panel(context, near, char_arm):
    """Standalone armature: an HSV wheel + value slider per colour and the sun handle."""
    coll = near.users_collection[0]
    arm = bpy.data.armatures.new(PANEL)
    arm.display_type = "WIRE"
    pan = bpy.data.objects.new(PANEL, arm)
    coll.objects.link(pan)
    bb = [near.matrix_world @ mathutils.Vector(c) for c in near.bound_box]
    pan.location = (max(v.x for v in bb) + 0.4, 0.0, max(v.z for v in bb) * 0.8)
    pan.show_in_front = True
    hb = _head_bone(char_arm)
    head = char_arm.matrix_world @ char_arm.data.bones[hb].head_local if hb else pan.location
    to_light = mathutils.Euler((0.9, 0.0, -0.5)).to_matrix() @ mathutils.Vector((0, 0, 1))  # front, above, to the side
    sun_at = head + to_light * SUN_DIST - pan.location
    prev = context.view_layer.objects.active
    context.view_layer.objects.active = pan
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    def bone(name, head, parent=None, length=0.03):
        b = eb.new(name)
        b.head, b.tail, b.parent = head, (head[0], head[1] + length, head[2]), parent
        return b

    root = bone("ST Panel", (0, 0, 0))
    for name, (ox, oz) in PICKERS.items():
        bone(f"ST {name} Center", (ox, 0, oz), root)
        bone(f"ST {name}", (ox, 0, oz), root)
        bone(f"ST {name} Value", (ox + SLIDER_DX, 0, oz), root)
    bone("ST Sun", tuple(sun_at), None, 0.05)
    bpy.ops.object.mode_set(mode="OBJECT")
    context.view_layer.objects.active = prev
    wheel_mat = _emission_mat("ST Wheel", _wheel_colour)
    ramp_mat = _emission_mat("ST Value Ramp", _ramp_colour)
    n = 64
    for name, (ox, oz) in PICKERS.items():
        disc = _mesh_obj(f"ST Wheel {name}", [(0, 0, 0)] + _circle(R, n), [(0, i + 1, (i + 1) % n + 1) for i in range(n)], pan, (ox, 0.005, oz), wheel_mat)
        h = VALUE_MAX * R
        track = _mesh_obj(f"ST Bar {name}", [(-0.006, 0, 0), (0.006, 0, 0), (0.006, 0, h), (-0.006, 0, h)], [(0, 1, 2, 3)], pan, (ox + SLIDER_DX, 0.005, oz), ramp_mat)
        label = bpy.data.objects.new(f"ST Label {name}", bpy.data.curves.new(f"ST Label {name}", "FONT"))
        label.data.body, label.data.size, label.data.align_x = name, 0.028, "CENTER"
        label.parent, label.location, label.rotation_euler = pan, (ox + 0.03, 0.005, oz + R + 0.04), (1.5708, 0, 0)
        label.hide_select = label.hide_render = True
        for ob in (disc, track, label):
            coll.objects.link(ob)
    for name in PICKERS:
        pan.pose.bones[f"ST {name} Value"].location = (0, 0, R)  # value 1 until a preset is applied
    return pan


def merge_panel(context, pan, rig):
    """Join the panel into the character rig (like Gacha Setup does with Genshin's panel), so
    lights animate in the same action as the character."""
    ui = list(pan.children)
    # offset from the panel origin (= ST Panel's head), not matrix_world: the panel was out of the
    # scene while Gacha rigged, so its children's world matrices are stale (~0.5-0.8 m behind)
    ui_off = {c: c.matrix_parent_inverse @ c.matrix_basis for c in ui}
    locs = {pb.name: pb.location.copy() for pb in pan.pose.bones}
    pan_mw = pan.matrix_world.copy()
    pan.parent = None
    pan.matrix_world = pan_mw
    if not pan.users_collection:
        rig.users_collection[0].objects.link(pan)
    context.view_layer.update()
    for o in context.view_layer.objects:
        o.select_set(False)
    pan.hide_set(False)
    pan.select_set(True)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for b in ("ST Panel", "ST Sun"):
        eb[b].parent = eb.get("root")
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, loc in locs.items():
        rig.pose.bones[name].location = loc
    context.view_layer.update()
    panel_mw = rig.matrix_world @ rig.pose.bones["ST Panel"].matrix
    for c in ui:
        c.parent, c.parent_type, c.parent_bone = rig, "BONE", "ST Panel"
        context.view_layer.update()
        c.matrix_world = panel_mw @ ui_off[c]
    coll = rig.data.collections_all.get(COLL) or rig.data.collections.new(COLL)
    for b in rig.data.bones:
        if b.name.startswith("ST "):
            for c in list(b.collections):
                c.unassign(b)
            coll.assign(b)
    coll.is_visible = True


def picker_bone(arm, name):
    """The picker bone of a colour in `arm` (characters imported up to 1.2 have two, with other names)."""
    return arm and next((b for b in (f"ST {name}", LEGACY_BONES.get(name)) if b and b in arm.data.bones), None)


def bind_lighting(context, arm, char_arm, mesh):
    """Pose settings, limits, drivers and sun constraints for the lighting controls in `arm`, which light
    `mesh`."""
    bind_settings(mesh, arm)
    ring = _mesh_obj("WGT-ST_picker", _circle(0.012), None, None, None)
    bar = _mesh_obj("WGT-ST_slider", [(-0.02, 0, 0), (0.02, 0, 0)], None, None, None)
    circ = _circle(0.03, 24)
    rays_out = [(0.06 * cos(tau * i / 8), 0, 0.06 * sin(tau * i / 8)) for i in range(8)]
    rays_in = [(0.04 * cos(tau * i / 8), 0, 0.04 * sin(tau * i / 8)) for i in range(8)]
    sun_w = _mesh_obj("WGT-ST_sun", circ + rays_out + rays_in, None, None, None,
                      edges=[(i, (i + 1) % 24) for i in range(24)] + [(24 + i, 32 + i) for i in range(8)])
    pb = arm.pose.bones
    for p in pb:
        if p.name.startswith("ST "):
            hidden = p.name == "ST Panel" or p.name.endswith(" Center")
            p.bone.hide = hidden
            p.hide = hidden  # Blender 5: pose-mode visibility lives on the pose bone
            p.use_custom_shape_bone_size = False  # widgets in metres, not scaled by the 3 cm bones
    for name in PICKERS:
        bone = picker_bone(arm, name)
        if not bone:
            continue
        p, s = pb[bone], pb[f"{bone} Value"]
        for bone_ in (p, s):
            for c in list(bone_.constraints):
                bone_.constraints.remove(c)
            # hidden with the Parameter Panel (Blender 5: pose-mode visibility lives on the pose bone)
            _drive(bone_, "hide", -1, "v", [("v", mesh, f'["{LIGHTING_TYPE}"]')])
        p.custom_shape, p.lock_location = ring, (False, True, False)
        p.lock_rotation = p.lock_scale = (True, True, True)
        c = p.constraints.new("LIMIT_DISTANCE")
        c.target, c.subtarget, c.limit_mode, c.distance = arm, f"{bone} Center", "LIMITDIST_INSIDE", R
        s.custom_shape, s.lock_location = bar, (True, True, False)
        s.lock_rotation = s.lock_scale = (True, True, True)
        lim = s.constraints.new("LIMIT_LOCATION")
        lim.owner_space, lim.use_min_z, lim.use_max_z, lim.min_z, lim.max_z = "LOCAL", True, True, 0.0, VALUE_MAX * R
    for o in arm.children:  # wheels, bars and labels; a modifier: a driven hide_viewport can't come back
        if o.name.startswith(("ST Wheel ", "ST Bar ", "ST Label ")):
            mod = o.modifiers.get(paper.HIDE) or o.modifiers.new(paper.HIDE, "NODES")
            mod.node_group = paper.hide_group()
            common.drive_modifier(mod, mesh, LIGHTING_TYPE, "v", 0, "")
            # hidden, it also sits on its parent: else Blender's dashed parent line still points at it
            o.delta_location = (0.0, 0.0, 0.0)
            away = o.matrix_parent_inverse.inverted().translation - o.location
            for i in range(3):
                _drive(o, "delta_location", i, f"v * {away[i]:.6f}", [("v", mesh, f'["{LIGHTING_TYPE}"]')])
    sol = pb["ST Sun"]
    sol.custom_shape = sun_w
    sol.lock_rotation = sol.lock_scale = (True, True, True)
    # light shines from the sun handle towards the head; the GN modifier reads ST_Light's rotation
    sun = mesh.get("st_light")
    hb = _head_bone(char_arm)
    if sun and hb:
        for c in list(sun.constraints):
            sun.constraints.remove(c)
        cl = sun.constraints.new("COPY_LOCATION")
        cl.name, cl.target, cl.subtarget = "ST Sun", arm, "ST Sun"
        dt = sun.constraints.new("DAMPED_TRACK")
        dt.name, dt.target, dt.subtarget, dt.track_axis = "ST Head", char_arm, hb, "TRACK_NEGATIVE_Z"


def _is_rig(arm):
    return "DEF-spine.006" in arm.data.bones and "root" in arm.data.bones


def ensure_lighting_panel(context, near):
    """Lighting controls in the rig: HSV wheels + value sliders + sun handle. Drivers copy each picker's
    position into a property of the character's mesh and the toon shader converts it to RGB."""
    char_arm = near.find_armature()
    if "ST Panel" in char_arm.data.bones:
        bind_lighting(context, char_arm, char_arm, near)
        return char_arm
    pan = own(near, "st_panel", lambda: create_panel(context, near, char_arm))
    if _is_rig(char_arm):
        del near["st_panel"]  # before the join: the pointer would keep the joined panel as an orphan
        merge_panel(context, pan, char_arm)
        bind_lighting(context, char_arm, char_arm, near)
        return char_arm
    attach_panel(context, pan, char_arm)
    bind_lighting(context, pan, char_arm, near)
    return pan


def attach_panel(context, pan, arm):
    """Make the standalone panel follow the character's root bone, keeping where it is now."""
    if pan and arm and "root" in arm.data.bones and (pan.parent, pan.parent_bone) != (arm, "root"):
        _reparent(context, pan, arm, "root")


# ---------- outline (inverted hull) ----------
OUTLINE_SUFFIX = " Outline"
OUTLINE_TINT = (0.19, 0.19, 0.28, 1.0)  # BaseColor of the game's outline materials (MI_*_Outline), times BaseMap
OUTLINE_WIDTH = 0.002  # metres; ~1.5 px at full-body 1080p like the reference videos
# shortcut: width is constant in world space (the game's looks screen-space) and the hull follows
# the mesh normals, not the smoothed normals packed in COL0.rgb; revisit if close-ups look too thick
# or hard edges show cracks.


def build_outline_gn():
    """Duplicate the deformed mesh, push it out along the normal by width * COL0.alpha (the game's
    outline mask: 0 on face/eyes), flip it and give each face its material's outline slot. Meshes
    without COL0 (weapons) get the outline everywhere."""
    ng, built = shared_group("ST Outline", "GeometryNodeTree")
    if built:
        return ng
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    w = sock(ng, "Width", "INPUT", "NodeSocketFloat", OUTLINE_WIDTH)
    w.min_value, w.max_value, w.subtype = 0.0, 0.02, "DISTANCE"
    sock(ng, "First Outline Slot", "INPUT", "NodeSocketInt", 0)
    nt = ng
    gi = node(nt, "NodeGroupInput", -1000, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    col = node(nt, "GeometryNodeInputNamedAttribute", -1000, -300, data_type="FLOAT_COLOR")
    col.inputs["Name"].default_value = "COL0"
    sep = node(nt, "FunctionNodeSeparateColor", -800, -300)
    nt.links.new(col.outputs["Attribute"], sep.inputs[0])
    # mask = COL0.alpha where the mesh has COL0, else 1: alpha * exists + (1 - exists)
    mask = math(nt, "ADD", math(nt, "MULTIPLY", sep.outputs["Alpha"], col.outputs["Exists"], -650, -350),
                math(nt, "SUBTRACT", 1.0, col.outputs["Exists"], -650, -450), -500, -400)
    keep = node(nt, "GeometryNodeDeleteGeometry", -600, 100, domain="FACE")
    nt.links.new(gi.outputs["Geometry"], keep.inputs["Geometry"])
    nt.links.new(math(nt, "LESS_THAN", mask, 0.01, -700, -100), keep.inputs["Selection"])
    nrm = node(nt, "GeometryNodeInputNormal", -600, -200)
    off = node(nt, "ShaderNodeVectorMath", -400, -200, operation="SCALE")
    nt.links.new(nrm.outputs["Normal"], off.inputs[0])
    nt.links.new(math(nt, "MULTIPLY", gi.outputs["Width"], mask, -550, -350), off.inputs["Scale"])
    sp = node(nt, "GeometryNodeSetPosition", -200, 100)
    nt.links.new(keep.outputs["Geometry"], sp.inputs["Geometry"])
    nt.links.new(off.outputs[0], sp.inputs["Offset"])
    flip = node(nt, "GeometryNodeFlipFaces", 0, 100)
    nt.links.new(sp.outputs["Geometry"], flip.inputs["Mesh"])
    idx = node(nt, "GeometryNodeInputMaterialIndex", 0, -150)
    smi = node(nt, "GeometryNodeSetMaterialIndex", 200, 100)
    nt.links.new(flip.outputs["Mesh"], smi.inputs["Geometry"])
    nt.links.new(math(nt, "ADD", idx.outputs[0], gi.outputs["First Outline Slot"], 100, -150), smi.inputs["Material Index"])
    join = node(nt, "GeometryNodeJoinGeometry", 500, 0)
    nt.links.new(smi.outputs["Geometry"], join.inputs[0])
    nt.links.new(gi.outputs["Geometry"], join.inputs[0])
    nt.links.new(join.outputs[0], go.inputs["Geometry"])
    return ng


def outline_material(src):
    """Dark tint of the source material's BaseMap; only the hull's camera-facing side shows."""
    name = src.name + OUTLINE_SUFFIX
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    base = next((n.image for n in src.node_tree.nodes if n.type == "TEX_IMAGE" and n.image
                 and n.image.colorspace_settings.name == "sRGB"), None) if src.node_tree else None
    tint = node(nt, "ShaderNodeRGB", -400, -150)
    tint.outputs[0].default_value = OUTLINE_TINT
    colour, alpha = tint.outputs[0], None
    if base:
        tex = node(nt, "ShaderNodeTexImage", -400, 150, image=base)
        colour = mix_rgb(nt, "MULTIPLY", 1.0, tex.outputs["Color"], tint.outputs[0], -150, 50)
        alpha = tex.outputs["Alpha"]
    em = node(nt, "ShaderNodeEmission", 100, 50)
    nt.links.new(colour, em.inputs["Color"])
    # hide the hull's back side (inverted hull) also in Cycles, where backface culling is ignored
    geo = node(nt, "ShaderNodeNewGeometry", 100, 300)
    cut = geo.outputs["Backfacing"]
    if alpha is not None:  # alpha-clipped parts (hair tips, lace) get no outline where they are cut
        cut = math(nt, "MAXIMUM", cut, math(nt, "LESS_THAN", alpha, 0.333, 150, -150), 250, 200)
    tr = node(nt, "ShaderNodeBsdfTransparent", 100, -100)
    mx = node(nt, "ShaderNodeMixShader", 400, 0)
    nt.links.new(cut, mx.inputs[0])
    nt.links.new(em.outputs[0], mx.inputs[1])
    nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    m.use_backface_culling = True
    m.surface_render_method = "DITHERED"
    return m


def ensure_outline(obj):
    me = obj.data
    while me.materials and me.materials[-1] and me.materials[-1].name.endswith(OUTLINE_SUFFIX):
        me.materials.pop()
    originals = list(me.materials)
    for src in originals:
        me.materials.append(outline_material(src))
    mod = obj.modifiers.get("ST Outline") or obj.modifiers.new("ST Outline", "NODES")
    mod.node_group = build_outline_gn()
    mod_input(mod, "First Outline Slot").value = len(originals)
    return mod


def mod_input(mod, name):
    # Blender 5.x: modifier inputs live in mod.properties.inputs.<identifier>.value
    return getattr(mod.properties.inputs, mod.node_group.interface.items_tree[name].identifier)


@functools.lru_cache(maxsize=1)
def _material_db():
    """materials.json, bundled with the add-on (tools/build_materials_db.py makes it from FModel's
    export): {material name lower-cased: {"<Character>/<Skin>" or "*": material data}}."""
    path = os.path.join(os.path.dirname(__file__), "materials.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bundled_material(name, skin, char_dir):
    """Material data from the bundled table: the entry of this character and skin if the material
    differs between skins, else the shared one. None if the material is not in the table."""
    entries = _material_db().get(name.lower())
    if not entries:
        return None
    char = os.path.basename(os.path.normpath(char_dir)) if char_dir else ""
    return (entries.get("*") or entries.get(f"{char}/{skin}")
            or next((v for k, v in entries.items() if k.endswith(f"/{skin}")), None) or next(iter(entries.values())))


def read_material(path):
    """Material data of a JSON exported with FModel, or None if it is something else: "Save Properties"
    writes another format under the same name, over the material's export."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError:  # truncated or not JSON
        return None
    return data if isinstance(data, dict) and "Textures" in data else None


def run(obj, char_dir):
    arm = obj.find_armature()
    mesh_skin = skin_of(obj.name, "")
    own = source_skin_dir(obj)
    tex_idx, json_idx = index_files(char_dir, prefer=own)
    sun, emp = ensure_rig(obj, arm)
    host = obj.get("st_light_host")
    if isinstance(host, bpy.types.Object):  # a paper version: lit by its 3D model's panel
        follow_settings(obj, host)
    else:
        ensure_lighting_panel(bpy.context, obj)  # after ensure_rig: it aims the sun with the sun handle
    ramp_image(char_dir)  # before the groups, which are reused once built
    toon_g, face_g = build_toon_group(), build_face_group()
    mod = obj.modifiers.get("ST Light Vectors") or obj.modifiers.new("ST Light Vectors", "NODES")
    mod.node_group = build_vectors_gn()
    for name, ob in zip(VECTOR_INPUTS, (sun, emp["Origin"], emp["Forward"], emp["Up"])):
        mod_input(mod, name).value = ob
    report = {}
    for slot in obj.material_slots:
        mat = slot.material
        if mat.name.endswith(OUTLINE_SUFFIX):
            continue
        base_name = re.sub(r"\.\d{3}$", "", mat.name)  # Blender adds .001 on name clashes (re-imports, FBX)
        skin = skin_of(base_name, mesh_skin)
        jp = pick(json_idx, base_name, skin)  # a JSON next to the textures wins (newer or edited export)
        data = read_material(jp) or bundled_material(base_name, skin, char_dir)
        if not data:
            report[mat.name] = NO_DATA
            continue
        setup_material(mat, data, tex_idx, mesh_skin, face_g, toon_g, report)
    ensure_outline(obj)
    return report


# ---------- weapons ----------
# Weapons use the game's MSM_Weapon shading: colour (_D), normal (_N), a packed _RMO texture and a
# metal matcap. Measured over several skins, the _RMO channels are R = emissive mask (black almost
# everywhere), G = roughness, B = metal (near 0 on painted skins like M82 S105): not occlusion, which
# blackened those skins. Here they get the characters' toon (same sun, same panel colours) so a weapon
# matches the hand that holds it, plus a matcap shine where RMO marks polished metal.
WEAPON_CLIP = 0.3333  # OpacityMaskClipValue of the weapon materials
WEAPON_VERSION = 7  # its own version: 3 = RMO read as emissive / roughness / metal; 4 = matcap UV without Vector Transform; 7 = panel colours, extra rim


def build_weapon_group():
    ng, built = shared_group("ST Weapon", "ShaderNodeTree", WEAPON_VERSION)
    if built:
        return ng
    sock(ng, "Shader", "OUTPUT", "NodeSocketShader")
    sock(ng, "MatCap UV", "OUTPUT", "NodeSocketVector")
    sock(ng, "Base Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    sock(ng, "Alpha", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Normal", "INPUT", "NodeSocketVector").hide_value = True
    sock(ng, "RMO", "INPUT", "NodeSocketColor", (0, 1, 0, 1))  # no glow, rough, no metal
    sock(ng, "MatCap", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    sock(ng, "Metal Shine", "INPUT", "NodeSocketFloat", 0.6)
    sock(ng, "Emissive", "INPUT", "NodeSocketFloat", 0.0)  # 1 when the material has EnableEmissive
    sock(ng, "Shadow Tint", "INPUT", "NodeSocketColor", SHADOW_TINT)
    sock(ng, "Middle Value", "INPUT", "NodeSocketFloat", 0.15)
    sock(ng, "Softness", "INPUT", "NodeSocketFloat", 0.03)
    nt = ng
    with section(nt, "Inputs", "in"):
        gi = node(nt, "NodeGroupInput", -900, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    with section(nt, "Light: N.L with the sun direction (lit side)", "light"):
        L = attr(nt, "lightDir", -700, 300)
        N = vmath(nt, "NORMALIZE", gi.outputs["Normal"], None, -700, 100).outputs[0]
        ndl = vmath(nt, "DOT_PRODUCT", N, L, -400, 200).outputs["Value"]
        lit = soft_step(nt, ndl, gi.outputs["Middle Value"], scaled_softness(nt, gi.outputs["Softness"], -700, -50), -200, 200)
        soft = math(nt, "MULTIPLY_ADD", ndl, 0.5, 0, 0)
        nt.nodes[-1].inputs[2].default_value = 0.5
    with section(nt, "MatCap UV (camera-space normal)", "tex"):
        nt.links.new(matcap_uv(nt, N, -500, -250), go.inputs["MatCap UV"])
    with section(nt, "RMO: R emission, G roughness, B metal", "tex"):
        rmo = node(nt, "ShaderNodeSeparateColor", -400, -450)
        nt.links.new(gi.outputs["RMO"], rmo.inputs[0])
    base = gi.outputs["Base Color"]
    col = toon_mix(nt, lit, soft, ndl, N, base, gi.outputs["Shadow Tint"], None, 100, 100)
    with section(nt, "Metal shine (matcap where the metal is polished) and emission", "color"):
        polish = math(nt, "MULTIPLY", rmo.outputs[2], math(nt, "SUBTRACT", 1.0, rmo.outputs[1], 300, -300), 450, -300)
        shine = math(nt, "MULTIPLY", polish, gi.outputs["Metal Shine"], 600, -300)
        col = mix_rgb(nt, "ADD", shine, col, gi.outputs["MatCap"], 650, 100)
        glow = math(nt, "MULTIPLY", rmo.outputs[0], gi.outputs["Emissive"], 600, -450)
        col = mix_rgb(nt, "ADD", glow, col, base, 800, 100)
    with section(nt, "Output (emission + alpha clip)", "out", extra=(go,)):
        clip = math(nt, "GREATER_THAN", gi.outputs["Alpha"], WEAPON_CLIP, 500, -150)
        shader_out(nt, col, clip, go, 650, -150)
    arrange_sections(nt)
    return ng


def setup_weapon_material(mat, data, tex_idx, weapon_group, report):
    t = {k: v["ObjectName"].split("'")[1] for k, v in data.get("Textures", {}).items() if v}
    skin = weapon_skin(mat.name)
    base_p = next((p for k in ("PM_Diffuse", "BaseColor_LOW", "BaseMap") for p in [pick(tex_idx, t.get(k, ""), skin)] if p), None)
    props = data.get("Properties", {}).get("BasePropertyOverrides", {})
    if not base_p:
        tint = data.get("Colors", {}).get("BaseColorTint")
        if tint and props.get("BlendMode") == "BLEND_Translucent":
            glass_material(mat, tint, data.get("Scalars", {}).get("OpacityScale", 0.5), report)
        elif any(t.get(k) for k in ("PM_Diffuse", "BaseColor_LOW", "BaseMap")):
            report[mat.name] = MISSING + next(t[k] for k in ("PM_Diffuse", "BaseColor_LOW", "BaseMap") if t.get(k))
        else:
            report[mat.name] = "sin textura de color, se deja igual"
        return
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    base = tex(nt, base_p, "sRGB", -600, 200)
    g = node(nt, "ShaderNodeGroup", 200, 0, node_tree=weapon_group)
    # second instance only provides the MatCap UV, so the texture -> group link is not a cycle
    g_uv = node(nt, "ShaderNodeGroup", -500, -350, node_tree=weapon_group, label="UV only")
    nt.links.new(base.outputs["Color"], g.inputs["Base Color"])
    nt.links.new(base.outputs["Alpha"], g.inputs["Alpha"])
    nt.links.new(g.outputs["Shader"], out.inputs["Surface"])
    used = [os.path.basename(base_p)]
    nrm_p = pick(tex_idx, t.get("PM_Normals") or t.get("N", ""), skin)
    normal, normal_label = normal_nodes(nt, nrm_p, (g, g_uv))
    if nrm_p:
        used.append(os.path.basename(nrm_p))
    extra = []
    rmo_p = pick(tex_idx, t.get("RM") or t.get("PM_SpecularMasks", ""), skin)
    if rmo_p:
        n = tex(nt, rmo_p, "Non-Color", -200, -450)
        nt.links.new(n.outputs["Color"], g.inputs["RMO"])
        used.append(os.path.basename(rmo_p))
        extra.append(("RMO: emision, rugosidad, metal", n))
    mc_p = pick(tex_idx, t.get("MatCapTex", ""), skin)
    if mc_p:
        n = tex(nt, mc_p, "sRGB", -200, -700, g_uv.outputs["MatCap UV"])
        nt.links.new(n.outputs["Color"], g.inputs["MatCap"])
        used.append(os.path.basename(mc_p))
        extra.append(("MatCap del metal", n))
    frame(nt, "Base texture (colour + alpha)", "tex", [base])
    frame(nt, normal_label, "tex", normal)
    frame(nt, "Computed UVs (MatCap)", "light", [g_uv])
    for label, n in extra:
        frame(nt, label, "tex", [n])
    if data.get("Switches", {}).get("EnableEmissive"):
        g.inputs["Emissive"].default_value = 1.0
    frame(nt, "Weapon toon (ST Weapon)", "color", [g])
    frame(nt, "Output", "out", [out])
    arrange_sections(nt)
    mat.surface_render_method = "BLENDED" if props.get("BlendMode") == "BLEND_Translucent" else "DITHERED"
    mat.use_backface_culling = not props.get("TwoSided", False)
    report[mat.name] = {"tipo": "arma", "texturas": used}


def glass_material(mat, tint, opacity, report):
    """A flat colour layer, partly transparent: sight lenses (unlit in the game) and the eyes' shadow."""
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    em = node(nt, "ShaderNodeEmission", 0, 100)
    em.inputs["Color"].default_value = (tint["R"], tint["G"], tint["B"], 1.0)
    tr = node(nt, "ShaderNodeBsdfTransparent", 0, -60)
    mx = node(nt, "ShaderNodeMixShader", 300, 0)
    mx.inputs[0].default_value = opacity
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    mat.surface_render_method = "BLENDED"
    mat.use_backface_culling = False
    report[mat.name] = {"tipo": "cristal", "texturas": []}


@functools.lru_cache(maxsize=2)
def _cached_index(root):
    return index_files(root)  # SkinAssets: ~20k files, ~1 s to walk


def shade_weapon(context, meshes, assets_root):
    """Toon shading for a weapon's meshes, lit on their own until connected to a hand."""
    weapon_g = build_weapon_group()
    light_weapon(meshes)

    def shade(tex_idx, json_idx):
        report = {}
        for m in meshes:
            for slot in m.material_slots:
                mat = slot.material
                if not mat or mat.name.endswith(OUTLINE_SUFFIX):
                    continue
                base = re.sub(r"\.\d{3}$", "", mat.name)
                jp = pick(json_idx, base, "")  # a JSON next to the textures wins (newer or edited export)
                data = read_material(jp) or bundled_material(base, weapon_skin(base), "")
                if not data:
                    report[mat.name] = NO_DATA
                    continue
                setup_weapon_material(mat, data, tex_idx, weapon_g, report)
        return report

    report = shade(*_cached_index(assets_root))
    if missing_textures(report) or NO_DATA in report.values():
        # the index is kept between imports: files exported since then are only found by walking again
        _cached_index.cache_clear()
        report = shade(*_cached_index(assets_root))
    for m in meshes:
        ensure_outline(m)
    return report


def light_weapon(meshes, host=None):
    """Light a weapon's meshes: with `host`'s sun and panel (the character whose hand holds it) or, on its
    own, with a sun and sidebar settings of its own, kept while it is in a hand. Called on import and when
    the weapon is connected or disconnected."""
    host = host if host and isinstance(host.get("st_light"), bpy.types.Object) else None
    lead = next((m for m in meshes if isinstance(m.get("st_own_light"), bpy.types.Object)), meshes[0])

    def new_sun():
        ob = bpy.data.objects.new(f"ST_Light {lead.name}", bpy.data.lights.new(f"ST_Light {lead.name}", "SUN"))
        ob.rotation_euler = (0.9, 0.0, -0.5)  # front, above, slightly to the side
        lead.users_collection[0].objects.link(ob)
        return ob

    sun = own(lead, "st_own_light", new_sun)
    sun.hide_viewport = sun.hide_render = bool(host)  # unused while in a hand
    if LIGHTING_TYPE not in lead:
        ensure_settings(lead)
        lead[LIGHTING_TYPE] = 1  # no wheels: always the sidebar's colours
    for m in [lead] + [m for m in meshes if m != lead]:
        m["st_light"] = host["st_light"] if host else sun
        m["st_weapon"], m["st_weapon_lead"] = True, lead
        if host:
            m["st_weapon_host"] = host
        elif "st_weapon_host" in m:
            del m["st_weapon_host"]
        mod = m.modifiers.get("ST Light Vectors") or m.modifiers.new("ST Light Vectors", "NODES")
        mod.node_group = build_vectors_gn()
        mod_input(mod, "Sun").value = m["st_light"]
        follow_settings(m, host or (None if m == lead else lead))
    if not host:
        bind_settings(lead, None)


@contextlib.contextmanager
def lighting_panel_aside(context, obj):
    """Gacha Setup rigs the wrong armature if our standalone lighting panel is in the scene: take it
    out while the rigger runs, then put it back where it was and join it into the new rig."""
    pan = obj.get("st_panel")
    colls = list(pan.users_collection) if pan else []
    mw = pan.matrix_world.copy() if pan else None  # its parent skeleton gets moved/replaced
    for c in colls:
        c.objects.unlink(pan)
    try:
        yield
    finally:
        for c in colls:
            c.objects.link(pan)
        if pan:
            pan.parent = None
            pan.matrix_world = mw
            ensure_lighting_panel(context, obj)  # joins the panel into the rig if there is one now


class STRINOVA_OT_setup(bpy.types.Operator):
    bl_idname = "strinova.setup_toon"
    bl_label = "Apply Toon Shading"
    bl_description = "Creates the node groups and the light/head rig, and rebuilds the character's materials"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_mesh(context) is not None

    def execute(self, context):
        obj = target_mesh(context)
        char_dir = bpy.path.abspath(context.scene.strinova_char_dir)
        if not os.path.isdir(char_dir):
            self.report({"ERROR"}, rpt_("Folder not found: {}").format(char_dir))
            return {"CANCELLED"}
        if not obj.find_armature():
            self.report({"ERROR"}, rpt_("{} has no armature").format(obj.name))
            return {"CANCELLED"}
        try:
            report = run(obj, char_dir)
        except KeyError as e:  # missing head bone
            self.report({"ERROR"}, rpt_("Bone not found: {}").format(e))
            return {"CANCELLED"}
        for k, v in report.items():
            print(f"[Strinova] {k}: {v}")
        done = sum(isinstance(v, dict) for v in report.values())
        miss = missing_textures(report)
        obj["st_missing_textures"] = len(miss)  # the importer repeats the warning in its own message
        if miss:
            self.report({"WARNING"}, rpt_("{} of {} materials without textures (e.g. {}): not found in {}. "
                                          "Check the Root folder").format(len(miss), len(report), miss[0], char_dir))
        else:
            self.report({"INFO"}, rpt_("{}/{} materials set up (details in the console)").format(done, len(report)))
        return {"FINISHED"}


classes = (STRINOVA_OT_setup,)
