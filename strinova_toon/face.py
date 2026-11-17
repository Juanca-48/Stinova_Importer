"""Face controls on top of Gacha Setup's face rig: gaze control for the eyeball bones, the
shape-key sliders sorted into sections (eyes, pupils, brows, mouth, phonemes, other) and, for the
few models with facial joints (*_SkinJNT), a control per joint.

Most Strinova skeletons have no face deformers besides the eyeballs (and eyelashes on some
characters): expressions are shape keys, which only the lobby models carry.
"""
import bpy, re, colorsys
import numpy as np
from math import pi
from mathutils import Matrix, Vector, kdtree
from . import shading, common

# ---------- shape key sections ----------
# Shape key names are pinyin + English and vary per character (biyanL, EL_mph48_biyan_L, B_close_L...).
# Built from the 390 names in the 506 lobby models. Each name is lower-cased, its prefix (EL_, mph48_...)
# removed, then: phonemes first, then the sections below in order, first pattern found wins; the rest
# goes to "Head & Other". Order matters: brows before mouth (base_smile_brow), pupils before eyes
# (eyeball_big, look_up), eyes before mouth (eye_C_smile).
PHONEMES = re.compile(r"(m_)?(pp|ff|th|dd|kk|ch|ss|nn|rr|aa|[aeiou]\d?|yi\d?|yi_?[lr]|wu\d?|ei\d?|em|sil|er|ga|ha|ju|mm|wo|xi)(_0)?")  # DD_0, SS_0 (HuiXing)
SECTIONS = (  # (section, ((regex, meaning), ...))
    ("Brows", (
        (r"^b_", "ceja (prefijo B_: B_close, B_up...)"),
        (r"brow", "ceja (base_*_brow)"),
        (r"meimao", "ceja (眉毛)"),
        (r"yamei", "ceja baja (压眉)"),
        (r"numei", "ceño enojado (怒眉)"),
        (r"tiaomei", "ceja alzada (挑眉)"),
        (r"bamei", "cejas tristes, en ocho (八字眉)"),
        (r"cumei|zhoumei", "ceño fruncido (蹙眉 / 皱眉)"),
        (r"mei", "ceja (眉)"),
    )),
    ("Pupils", (
        (r"tongkong|tk", "pupila (瞳孔, TK)"),
        (r"xitong", "pupila rasgada (细瞳)"),
        (r"eyeball", "globo ocular"),
        (r"mydriasis", "pupila dilatada"),
        (r"bulging", "ojos saltones"),
        (r"douji", "bizco (斗鸡眼)"),
        (r"^look_|^eye_(up|down|left|right|l|r)$", "mirada arriba / abajo / a un lado"),
        (r"light|hl_|[dx]gg", "brillo del ojo (高光: grande DGG, pequeño XGG)"),
    )),
    ("Eyes", (
        (r"^o_o$|^=(_[lr])?$", "ojos en blanco / cerrados en línea (o_o, =_=)"),
        (r"biyan", "cerrar el ojo (闭眼)"),
        (r"dengyan", "ojo muy abierto (瞪眼)"),
        (r"pin(g)?yan", "ojo entrecerrado, plano (平眼)"),
        (r"miyan", "ojo entornado (眯眼)"),
        (r"xiaoyan", "ojo sonriente (笑眼)"),
        (r"banyan", "ojo medio cerrado (半眼)"),
        (r"xieyan", "mirada de reojo (斜眼)"),
        (r"muyan", "mirada vacía (木眼)"),
        (r"xiayanpi", "párpado inferior (下眼皮)"),
        (r"yanjiao", "comisura del ojo (眼角; nei = interior, wai = exterior)"),
        (r"yan", "ojo (眼)"),
        (r"eye", "ojo / párpado (eye, upEye, eye_C_smile...)"),
        (r"angrywei|trguan", "mirada enojada, lágrimas (Mara; medido: mueven la zona del ojo)"),
    )),
    ("Mouth", (
        (r"^m_|^mop", "boca (prefijo M_ / Mop)"),
        (r"zuijiao", "comisura de la boca (嘴角)"),
        (r"duzui", "puchero (嘟嘴)"),
        (r"zui", "boca (嘴: miaozui, MiZhui...)"),
        (r"sanjiao", "boca triangular (三角嘴)"),
        (r"ganga", "mueca incómoda (尴尬)"),
        (r"tushe|tongue", "lengua afuera (吐舌头)"),
        (r"tooth", "dientes"),
        (r"mouth|lip|smile", "boca, labios, sonrisa"),
        (r"^ta$|^mi$", "boca de 'ta' / 'mi'"),
    )),
)  # not listed, so "Head & Other": tou (头, cabeza), gulian (鼓脸, mejillas infladas), bizi / nose (鼻子,
#   nariz), jaw (mandíbula), and per-character effects (faceM, Maddelena_Face_V006, MiZhui moves nothing)
ORDER = ("Eyes", "Pupils", "Brows", "Mouth", "Lips", "Head & Other")  # Boca: opens the mouth (+ phonemes); Labios: keeps it closed
COLS, DX, DY = 6, 0.019, 0.039  # Gacha's slider spacing
SECTION_GAP = 0.04
FACE_HALF = 0.18  # keep the face clear, like Gacha: eye sections on its left, mouth ones on its right
LABEL_DZ = 0.019  # label above the first row
LABEL_SCALE = 0.011
# Ojos, Pupilas and Cejas split into: both sides on top, then right and left. Each block sits on the
# side of the face it moves as seen from the front: *_L keys move the character's left (+X, measured),
# which is the viewer's right, so Izquierda goes right and Derecha left.
SIDED = ("Eyes", "Pupils", "Brows")
SIDES = (("", "Both"), ("R", "Right"), ("L", "Left"))
SIDE_COLS = 3
SIDE_GAP = 2 * DX  # between the Derecha and Izquierda blocks
# one bright hue per sub-group (Blender's preset color sets include near-black ones), stepping 5/13
# of the wheel so neighbouring frames contrast; 13 = 3 sides x Ojos/Pupilas/Cejas + 4 plain sections
SUB_COLORS = [colorsys.hsv_to_rgb((i * 5 % 13) / 13, 0.75, 0.95) for i in range(13)]
SUB_DZ = 0.02  # sub-label above its rows
SUB_SCALE = 0.007
FRAME_PAD = 0.006  # margin of each frame around what it holds
PLAIN_DROP = 0.012  # sections without sub-groups: sliders lowered so their frame clears the title
SLIDER_TRAVEL = 0.0101  # Gacha's slider: local Z from 0 (key 0) to this (key 1)
HANDLE_HALF_W, HANDLE_HALF_H = 0.006, 0.0012  # sliding bar
TICK_HALF_W = 0.0035  # guide marks at the min and max


def face_collection(rig, name, row):
    """Bone collection inside "Face" (hiding Face hides all), with a button row in Rigify's panel."""
    face = rig.data.collections_all.get("Face") or rig.data.collections.new("Face")
    coll = rig.data.collections_all.get(f"Face: {name}") or rig.data.collections.new(f"Face: {name}", parent=face)
    if hasattr(coll, "rigify_ui_row"):  # only while Rigify is enabled
        coll.rigify_ui_row, coll.rigify_ui_title = row, name
    return coll


def section_of(key):
    k = re.sub(r"^(el_|eb_|mth_)?(mph\d+_)?", "", key.lower())
    if PHONEMES.fullmatch(k):
        return "Phonemes"
    return next((name for name, rows in SECTIONS for pat, _ in rows if re.search(pat, k)), "Head & Other")


OPEN_MIN = 0.004  # lips this much further apart = the key opens the mouth (measured: 10-19 mm open, <3 mm not)
LIP_GAP = 0.0015  # closed lips: upper and lower lip vertices this close at rest, not joined by an edge


def opening_keys(mesh, names):
    """The shape keys in `names` that open the mouth. The mouth is closed at rest, so upper and lower
    lip vertices sit almost on top of each other without sharing an edge; a key opens the mouth if it
    pulls such a pair apart. Only the face skin counts: teeth and tongue are separate pieces that
    move inside a closed mouth. If no such pairs are found, every key counts as opening."""
    me, kb = mesh.data, mesh.data.shape_keys.key_blocks
    n = len(me.vertices)
    R = np.array(mesh.matrix_world.to_3x3())

    def co(k):
        a = np.empty(n * 3)
        k.data.foreach_get("co", a)
        return a.reshape(-1, 3) @ R.T

    base = co(kb[0])
    shapes = {name: co(kb[name]) for name in names if name in kb}
    region = np.zeros(n, bool)
    for c in shapes.values():
        region |= np.linalg.norm(c - base, axis=1) > 0.0005
    edges = {tuple(sorted(e.vertices)) for e in me.edges}
    parent = list(range(n))  # connected pieces (union-find)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[ra] = rb
    piece = np.array([root(i) for i in range(n)])
    if not region.any():
        return set(shapes)
    ids, counts = np.unique(piece[region], return_counts=True)
    idx = np.nonzero(region & (piece == ids[np.argmax(counts)]))[0]  # the face skin around the mouth
    kd = kdtree.KDTree(len(idx))
    for i in idx:
        kd.insert(base[i], int(i))
    kd.balance()
    pairs = np.array(sorted({(min(i, j), max(i, j)) for i in idx for _, j, _ in kd.find_range(base[i], LIP_GAP)
                             if j != i and (min(i, j), max(i, j)) not in edges}))
    if not len(pairs):
        return set(shapes)
    rest = np.linalg.norm(base[pairs[:, 0]] - base[pairs[:, 1]], axis=1)
    out = set()
    for name, c in shapes.items():
        grow = np.sort(np.linalg.norm(c[pairs[:, 0]] - c[pairs[:, 1]], axis=1) - rest)
        if grow[-min(3, len(grow))] > OPEN_MIN:  # third largest: one stray pair is not an open mouth
            out.add(name)
    return out


def side_of(key):
    """'L', 'R' or '' (both). Case matters: an upper-case L/R ending marks the side (biyanL,
    B_close_L), while eyeball_small or eye_L / look_left (both pupils looking left) are both."""
    k = re.sub(r"^(EL_|EB_|Mth_)?(mph\d+_)?", "", key, flags=re.I)
    if re.fullmatch(r"(?i)(eye|look)_(l|r|left|right)", k):
        return ""
    m = re.search(r"(?<![A-Z])([LR])$", k)
    return m.group(1) if m else ""


def section_layout(name, bones, sides):
    """({slider: (dx, dz)}, [(sub-label, dx, dz)], width, [(sub-label or None, sliders)]) from the
    section's top-left corner; the last item lists the blocks that get an inner frame."""
    groups = {s: [] for s, _ in SIDES}
    for b in bones:
        groups[sides[b] if name in SIDED else ""].append(b)
    if not (groups["L"] or groups["R"]):  # one plain grid
        pos = {b: ((i % COLS) * DX, -PLAIN_DROP - (i // COLS) * DY) for i, b in enumerate(bones)}
        return pos, [], (min(len(bones), COLS) - 1) * DX, [(None, bones)]
    side_w = (SIDE_COLS - 1) * DX
    width = 2 * side_w + SIDE_GAP
    pos, subs, z = {}, [], 0.0
    both = groups[""]
    if both:
        grid_w = (min(len(both), COLS) - 1) * DX
        subs.append(("Both", width / 2, z))
        for i, b in enumerate(both):
            pos[b] = ((width - grid_w) / 2 + (i % COLS) * DX, z - SUB_DZ - (i // COLS) * DY)
        z -= SUB_DZ + ((len(both) - 1) // COLS + 1) * DY
    for (side, label), x0 in zip(SIDES[1:], (0.0, side_w + SIDE_GAP)):  # R block at -X, L block at +X
        if groups[side]:
            subs.append((label, x0 + side_w / 2, z))
        for i, b in enumerate(groups[side]):
            pos[b] = (x0 + (i % SIDE_COLS) * DX, z - SUB_DZ - (i // SIDE_COLS) * DY)
    return pos, subs, width, [(label, groups[s]) for s, label in SIDES if groups[s]]


def text_widget(text):
    """Outline text in the XZ plane (like Gacha's labels), shared by every rig."""
    name = f"WGT-ST_face_{text}"
    ob = bpy.data.objects.get(name)
    if ob:
        return ob
    cu = bpy.data.curves.new(name, "FONT")
    cu.body, cu.align_x, cu.fill_mode = text, "CENTER", "NONE"  # outline only
    tmp = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(tmp)
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    # text is drawn in XY; label bones point at the viewer (-Y), whose local X is the world's -X
    me.transform(Matrix.Scale(-1, 4, (1, 0, 0)) @ Matrix.Rotation(pi / 2, 4, "X"))
    return bpy.data.objects.new(name, me)


def slider_sides(rig, mesh, keys):
    """{slider: 'L' / 'R' / ''}. The name says whether a key is one-sided (biyan_L), but not which
    side: in the mph48_biyan_L family _L moves the character's left, in the upEye_C_L family its
    right. So the side is measured: where the key moves the mesh, left (+X) or right of the face."""
    sk = mesh.data.shape_keys
    n = len(mesh.data.vertices)
    m = np.array(rig.matrix_world.inverted() @ mesh.matrix_world)
    root = rig.data.bones.get("Face-Root")
    mid = root.head_local.x if root else 0.0

    def x_of(name):
        k = sk.key_blocks[name]
        a, b = np.empty(n * 3), np.empty(n * 3)
        k.data.foreach_get("co", a)
        k.relative_key.data.foreach_get("co", b)
        d = np.linalg.norm((a - b).reshape(-1, 3), axis=1)
        moved = d > 0.0005
        if not moved.any():
            return None
        x = (m[0, :3] @ a.reshape(-1, 3)[moved].T) + m[0, 3]
        return float(np.average(x, weights=d[moved])) - mid

    out = {}
    for b, (_, key) in keys.items():
        side = "" if b == BLINK else side_of(key)
        x = x_of(key) if side else None
        out[b] = side if x is None or abs(x) < 0.002 else ("L" if x > 0 else "R")
    return out


BLINK = "CTRL-ST Blink"
CLOSE_EYE = (  # keys that close one eye, by preference: biyan (闭眼: biyan_L, biyanR, mph48_biyan_L), else
    re.compile(r"(^|_)biyan_?([lr])$"),  # eye_C_smile_L (upEye_C / downEye_C family: both lids at once,
    re.compile(r"^eye_c_smile_([lr])$"),  # measured: upper lid -5 mm, lower +3 mm)
)


def add_blink(context, rig, mesh):
    """Models that close each eye with its own key (biyan_L / biyan_R, or eye_C_smile_L / _R) and have no key for both get
    a blink slider: it drives both keys on top of their own sliders (driver value = own + blink,
    up to 1), so winks still work. Returns False when the model has no such pair or already blinks."""
    keys = slider_keys(mesh)
    if BLINK in rig.data.bones or not keys:
        return False
    found = [{} for _ in CLOSE_EYE]  # per pattern: side -> (slider, key)
    for b, (_, key) in keys.items():
        if section_of(key) == "Eyes" and not side_of(key) and re.search(r"(?i)biyan|blink|close", key):
            return False  # it already has a blink
        k = re.sub(r"^(el_|eb_|mth_)?(mph\d+_)?", "", key.lower())
        for pat, sides in zip(CLOSE_EYE, found):
            m = pat.search(k)
            if m:
                sides.setdefault(m.group(m.lastindex), (b, key))
    close = next((s for s in found if set(s) == {"l", "r"}), None)
    if not close:
        return False
    template = close["l"][0]
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    e = eb.new(BLINK)
    e.head, e.tail, e.roll, e.parent = eb[template].head, eb[template].tail, eb[template].roll, eb[template].parent
    e.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")
    src, pb = rig.pose.bones[template], rig.pose.bones[BLINK]
    pb.lock_location, pb.lock_rotation, pb.lock_scale = src.lock_location, src.lock_rotation, src.lock_scale
    travel = SLIDER_TRAVEL
    for c in src.constraints:
        if c.type == "LIMIT_LOCATION":
            n = pb.constraints.new("LIMIT_LOCATION")
            for attr in ("use_min_x", "use_max_x", "use_min_y", "use_max_y", "use_min_z", "use_max_z", "min_x", "max_x",
                         "min_y", "max_y", "min_z", "max_z", "owner_space", "use_transform_limit"):
                setattr(n, attr, getattr(c, attr))
            travel = c.max_z or travel
    for d in mesh.data.shape_keys.animation_data.drivers:
        if d.data_path not in (f'key_blocks["{close[s][1]}"].value' for s in "lr"):
            continue
        v = d.driver.variables.new()
        v.name, v.type = "parpadeo", "TRANSFORMS"
        v.targets[0].id, v.targets[0].bone_target = rig, BLINK
        v.targets[0].transform_type, v.targets[0].transform_space = "LOC_Z", "LOCAL_SPACE"
        d.driver.expression = f"min(1.0, {d.driver.expression} + max(0.0, parpadeo / {travel}))"
    return True


def slider_keys(mesh):
    """{slider bone: (first key index, key name)} from the shape-key drivers Gacha made."""
    out = {}
    sk = mesh.data.shape_keys
    if not (sk and sk.animation_data):
        return out
    index = {k.name: i for i, k in enumerate(sk.key_blocks)}
    for d in sk.animation_data.drivers:
        m = re.fullmatch(r'key_blocks\["(.+)"\]\.value', d.data_path)
        if not (m and m.group(1) in index):
            continue
        for v in d.driver.variables:  # every slider of the key: its own and, for the eyes, the blink
            bone = v.targets[0].bone_target
            if bone.startswith("CTRL-"):
                out[bone] = min(out.get(bone, (1e9, "")), (index[m.group(1)], m.group(1)))
    return out


def arrange_face(context, rig, mesh):
    """Move Gacha's face sliders into labelled sections and give each section a bone collection
    (inside "Face"). Sliders only move, so their drivers (local Z) keep working."""
    keys = slider_keys(mesh)
    if not keys:
        return
    groups = {}
    for bone, (i, key) in sorted(keys.items(), key=lambda kv: kv[1]):
        groups.setdefault(section_of(key), []).append(bone)
    if groups.get("Mouth"):  # split by what each key does: opens the mouth (Boca) or only moves the lips
        opens = opening_keys(mesh, [keys[b][1] for b in groups["Mouth"]])
        groups["Lips"] = [b for b in groups["Mouth"] if keys[b][1] not in opens]
        groups["Mouth"] = [b for b in groups["Mouth"] if keys[b][1] in opens]
    groups["Mouth"] = groups.get("Mouth", []) + groups.pop("Phonemes", [])  # phonemes join the mouth section
    for s in ("Mouth", "Lips"):
        if not groups.get(s):
            groups.pop(s, None)
    sides = slider_sides(rig, mesh, keys)
    layouts = {name: section_layout(name, bones, sides) for name, bones in groups.items()}
    # text widgets need object mode; their size sets the frames
    texts = set(groups) | {t for lay in layouts.values() for t, _, _ in lay[1]}
    text_box = {}
    for t in texts:
        vs = [v.co for v in text_widget(t).data.vertices]
        text_box[t] = (min(v.x for v in vs), max(v.x for v in vs), min(v.z for v in vs), max(v.z for v in vs))
    frame = frame_widget()
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    old = [b for b in eb if b.name.startswith(("LABEL-", "FRAME-ST", "GUIDE-ST"))]
    heads = [eb[b].head for b in keys] + [b.head for b in old if b.name.startswith("LABEL-")]
    top = max(h.z for h in heads)
    y = eb[next(iter(keys))].head.y
    root = eb.get("Face-Root")
    mid = root.head.x if root else 0.0
    for b in old:
        eb.remove(b)

    left, right = [s for s in ORDER[:3] if s in groups], [s for s in ORDER[3:] if s in groups]
    starts = {}
    x = mid - FACE_HALF - sum(layouts[s][2] for s in left) - SECTION_GAP * (len(left) - 1)
    for name in left + right:
        if name == (right or [None])[0]:
            x = mid + FACE_HALF
        starts[name] = x
        x += layouts[name][2] + SECTION_GAP

    def move(e, coll, at):
        off = Vector(at) - e.head
        e.head += off
        e.tail += off
        for c in list(e.collections):
            c.unassign(e)
        coll.assign(e)

    def label_rect(e, text, scale):
        x0, x1, z0, z1 = text_box[text]
        h = e.head
        return h.x + x0 * scale, h.z + z0 * scale, h.x + x1 * scale, h.z + z1 * scale

    def slider_rect(e):  # bar at rest plus its travel up
        h = e.head
        return h.x - HANDLE_HALF_W, h.z - HANDLE_HALF_H, h.x + HANDLE_HALF_W, h.z + SLIDER_TRAVEL + HANDLE_HALF_H

    def union(rects, pad):
        return (min(r[0] for r in rects) - pad, min(r[1] for r in rects) - pad,
                max(r[2] for r in rects) + pad, max(r[3] for r in rects) + pad)

    face_coll = rig.data.collections_all.get("Face") or rig.data.collections.new("Face")
    labels, frames = [], []  # (bone, text, scale), (bone, rect)

    def add_frame(name, rect, coll):
        f = eb.new(f"FRAME-ST {name}")
        f.tail = (0, -0.005, 0)
        f.parent = root
        move(f, coll, ((rect[0] + rect[2]) / 2, y, (rect[1] + rect[3]) / 2))
        frames.append((f.name, rect))

    side_rects = {"izquierda": [], "derecha": []}
    colored = []  # one bone list per sub-group, in reading order
    guides = []
    for name in left + right:
        pos, subs, width, blocks = layouts[name]
        x, z = starts[name], top - LABEL_DZ  # z: top of the sliders / sub-labels
        coll = face_collection(rig, name, 2 + ORDER.index(name) // 3)
        sub_bone = {}
        for text, dx, dz, scale, bone in [(name, width / 2, LABEL_DZ, LABEL_SCALE, f"LABEL-ST {name}")] + \
                [(t, dx, dz, SUB_SCALE, f"LABEL-ST {name} {t}") for t, dx, dz in subs]:
            lab = eb.new(bone)
            lab.tail = (0, -0.005, 0)
            lab.parent = root
            move(lab, coll, (x + dx, y, z + dz))
            labels.append((lab.name, text, scale))
            sub_bone[text] = lab
        for b, (dx, dz) in pos.items():
            move(eb[b], coll, (x + dx, y, z + dz))
            g = eb.new(f"GUIDE-ST {b}")  # fixed track behind the bar: same axes, so its Z is the travel
            g.head, g.tail, g.roll, g.parent = eb[b].head, eb[b].tail, eb[b].roll, root
            move(g, coll, eb[b].head)
            guides.append(g.name)
        rects = [label_rect(sub_bone[name], name, LABEL_SCALE)]
        for sub, bones in blocks:  # inner frame per sub-group (or around the whole grid)
            inner = [slider_rect(eb[b]) for b in bones]
            if sub:
                inner.append(label_rect(sub_bone[sub], sub, SUB_SCALE))
            rect = union(inner, FRAME_PAD)
            add_frame(f"{name} {sub or ''}".strip(), rect, coll)
            colored.append(list(bones) + [f"GUIDE-ST {b}" for b in bones] + [frames[-1][0]])  # one color each
            rects.append(rect)
        side_rects["izquierda" if name in left else "derecha"].append(union(rects, 0))
    for side, rects in side_rects.items():  # outer frame per side of the face
        if rects:
            add_frame(side, union(rects, FRAME_PAD), face_coll)
    bpy.ops.object.mode_set(mode="OBJECT")
    for c in list(face_coll.children):  # sections that no longer exist (an older rig's Cara: Fonemas)
        if c.name.startswith(("Cara: ", "Face: ")) and c.name[6:] in ("Fonemas", "Phonemes") and not c.bones:
            rig.data.collections.remove(c)
    for names, rgb in zip(colored, SUB_COLORS):
        for n in names:
            common.paint(rig, n, rgb)
    for n, text, scale in labels:
        pb = rig.pose.bones[n]
        pb.custom_shape = text_widget(text)
        pb.custom_shape_scale_xyz = (scale,) * 3
        pb.use_custom_shape_bone_size = False
        pb.lock_location = pb.lock_rotation = pb.lock_scale = (True, True, True)
    for n, (x0, z0, x1, z1) in frames:
        pb = rig.pose.bones[n]
        pb.custom_shape = frame
        pb.custom_shape_scale_xyz = (x1 - x0, 1, z1 - z0)  # unit square scaled to the box
        pb.use_custom_shape_bone_size = False
        pb.lock_location = pb.lock_rotation = pb.lock_scale = (True, True, True)
        pb.bone.hide_select = True  # decoration: clicks go to the sliders
    bar = frame_widget()  # same unit square, as a flat bar
    for b in keys:
        pb = rig.pose.bones[b]
        pb.custom_shape = bar
        pb.custom_shape_scale_xyz = (2 * HANDLE_HALF_W, 1, 2 * HANDLE_HALF_H)
        pb.use_custom_shape_bone_size = False
        pb.custom_shape_wire_width = 2
    track = guide_widget()
    for n in guides:
        pb = rig.pose.bones[n]
        lim = next((c for c in rig.pose.bones[n[len("GUIDE-ST "):]].constraints if c.type == "LIMIT_LOCATION"), None)
        pb.custom_shape = track
        pb.custom_shape_scale_xyz = (TICK_HALF_W, 1, lim.max_z if lim else SLIDER_TRAVEL)  # marks at min and max
        pb.use_custom_shape_bone_size = False
        pb.lock_location = pb.lock_rotation = pb.lock_scale = (True, True, True)
        pb.bone.hide_select = True  # guide only: clicks go to the bar


def frame_widget():
    """Unit square in the XZ plane, centred, scaled per frame."""
    return shading._mesh_obj("WGT-ST_frame", [(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)], None, None, None)


def guide_widget():
    """Slider track: a line from 0 to 1 up Z with a mark at each end, scaled per slider to its travel."""
    verts = [(0, 0, 0), (0, 0, 1), (-1, 0, 0), (1, 0, 0), (-1, 0, 1), (1, 0, 1)]
    return shading._mesh_obj("WGT-ST_slider_guide", verts, None, None, None, edges=[(0, 1), (2, 3), (4, 5)])


# ---------- facial bones ----------
JNT = "_SkinJNT"  # Maya-style facial joints (Fragrans, Yugiri, Mara lobby; Chiyo's in-match eyelids)
INNER = ("Tooth", "Tongue")  # inside the mouth: own collection, hidden by default
JNT_R, LIP_R = 0.003, 0.0018  # widget radius; lip joints sit 4 mm apart
JNT_SPREAD = 0.004  # upper/lower lip joints are 1 mm apart: push their widgets up/down
JNT_FORWARD = 0.015  # widgets in front of the skin


def add_face_bones(rig, mesh):
    """Facial deform joints, when the model has them, become controls in "Face: Bones": a small
    circle facing front (custom shape rotated out of each joint's own axes) coloured by side.
    Models without them keep only the shape key sliders."""
    weighted = {g.name for g in mesh.vertex_groups if g.name.endswith(JNT)}
    bones = [b for b in rig.data.bones if b.name.endswith(JNT) and b.name in weighted
             and not b.name.startswith("Facial_Master")]  # the master moves the whole face
    if not bones:
        return
    shape = shading._mesh_obj("WGT-ST_face_joint", shading._circle(1.0, 16), None, None, None)
    main, inner = face_collection(rig, "Bones", 4), face_collection(rig, "Inner Mouth", 4)
    inner.is_visible = False
    colors = {"Left": SUB_COLORS[0], "Right": SUB_COLORS[1]}
    for b in bones:
        n = b.name
        for c in list(b.collections):
            c.unassign(b)
        (inner if n.startswith(INNER) or n[:-len(JNT)].endswith(INNER) else main).assign(b)
        off = Vector((0, -JNT_FORWARD, 0))
        if re.search(r"(^|_)Up", n):  # Left_UpLid2, Mid_Lip_Up, Up_Tooth
            off.z += JNT_SPREAD
        elif re.search(r"(^|_)(Dn|Down)", n):
            off.z -= JNT_SPREAD
        if n.startswith("Jaw"):
            off = Vector((0, -0.05, -0.05))  # at the chin, clear of the nose and lips
        rot = b.matrix_local.to_3x3().inverted()  # widget axes back to the rig's (faces -Y)
        pb = rig.pose.bones[n]
        pb.custom_shape = shape
        pb.use_custom_shape_bone_size = False
        pb.custom_shape_scale_xyz = (LIP_R if "Lip" in n else JNT_R,) * 3
        pb.custom_shape_rotation_euler = rot.to_euler()
        pb.custom_shape_translation = rot @ off
        common.paint(rig, n, colors.get(n.split("_")[0], SUB_COLORS[2]))


# ---------- gaze ----------
GAZE = "Gaze"
GAZE_DIST = 0.35  # target distance in front of the eyes (m)


def add_gaze(context, rig):
    """One target in front of the face (follows the head) with a sub-target per eye. Each eyeball
    hangs from a helper bone that points forward and damped-tracks its target: the eyeball bones
    don't point forward, so tracking them directly would turn them in the rest pose."""
    eyes = {s: f"eye_{s.lower()}_ball_01" for s in "LR" if f"eye_{s.lower()}_ball_01" in rig.data.bones}
    if len(eyes) < 2 or GAZE in rig.data.bones:
        return False
    head = "head" if "head" in rig.data.bones else "ORG-spine.006"
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    pos = {s: eb[n].head.copy() for s, n in eyes.items()}
    cy = sum(p.y for p in pos.values()) / 2 - GAZE_DIST  # model faces -Y
    cz = sum(p.z for p in pos.values()) / 2
    main = eb.new(GAZE)
    main.head, main.tail, main.parent = (0, cy, cz), (0, cy + 0.04, cz), eb[head]
    for s, n in eyes.items():
        t = eb.new(f"{GAZE}.{s}")
        t.head, t.tail, t.parent = (pos[s].x, cy, cz), (pos[s].x, cy + 0.02, cz), main
        mch = eb.new(f"MCH-{GAZE}.{s}")
        mch.head, mch.tail, mch.parent = pos[s], pos[s] + Vector((0, -0.03, 0)), eb[n].parent
        mch.use_deform = False
        eb[n].use_connect = False
        eb[n].parent = mch
    bpy.ops.object.mode_set(mode="OBJECT")
    gaze = face_collection(rig, GAZE, 4)
    hidden = rig.data.collections_all.get("Other") or rig.data.collections.new("Other")
    ellipse = [(0.06 * x, 0, 0.025 * z) for x, _, z in shading._circle(1.0)]
    shapes = {GAZE: shading._mesh_obj("WGT-ST_gaze", ellipse, None, None, None),
              "eye": shading._mesh_obj("WGT-ST_gaze_eye", shading._circle(0.012), None, None, None)}
    for n in [GAZE] + [f"{GAZE}.{s}" for s in eyes]:
        b, pb = rig.data.bones[n], rig.pose.bones[n]
        gaze.assign(b)
        pb.custom_shape = shapes[GAZE if n == GAZE else "eye"]
        pb.use_custom_shape_bone_size = False
        pb.lock_rotation = pb.lock_scale = (True, True, True)
    for s in eyes:
        hidden.assign(rig.data.bones[f"MCH-{GAZE}.{s}"])
        c = rig.pose.bones[f"MCH-{GAZE}.{s}"].constraints.new("DAMPED_TRACK")
        c.name, c.target, c.subtarget, c.track_axis = "ST Gaze", rig, f"{GAZE}.{s}", "TRACK_Y"
    return True
