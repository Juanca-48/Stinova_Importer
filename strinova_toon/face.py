"""Face controls on top of Gacha Setup's face rig: gaze control for the eyeball bones and the
shape-key sliders sorted into sections (eyes, pupils, brows, mouth, phonemes, other).

Strinova's skeleton has no face deformers besides the eyeballs (and eyelashes on some
characters): expressions are shape keys, which only the lobby models carry.
"""
import bpy, re
from math import pi
from mathutils import Matrix, Vector
from . import shading

# ---------- shape key sections ----------
# Names are pinyin + English and vary per character (biyanL, EL_mph48_biyan_L, B_close_L...):
# yan = eye, mei = brow, zui = mouth, tongkong = pupil, tou = head.
PHONEMES = re.compile(r"(m_)?(pp|ff|th|dd|kk|ch|ss|nn|rr|aa|[aeiou]\d?|yi\d?|yi_?[lr]|wu\d?|ei\d?|em|sil|er|ga|ha|ju|mm|wo|xi)")
SECTIONS = (  # first match wins; phonemes are checked before, the rest falls into "Cabeza y otros"
    ("Cejas", r"mei|brow|^b_"),
    ("Pupilas", r"look_|^eye_(up|down|left|right|l|r)$|tongkong|xitong|light|tk_|eyeball|mydriasis|hl_|gg(big|dong|guan)"),
    ("Ojos", r"yan|eye|o_o|^=_"),
    ("Boca", r"zui|mouth|^m_|tooth|tongue|tushe|lip|smile|^ta$|^mi$"),
)  # jaw and cheeks (gulian) go to "Cabeza y otros" on purpose
ORDER = ("Ojos", "Pupilas", "Cejas", "Boca", "Fonemas", "Cabeza y otros")
COLS, DX, DY = 6, 0.019, 0.039  # Gacha's slider spacing
SECTION_GAP = 0.04
FACE_HALF = 0.18  # keep the face clear, like Gacha: eye sections on its left, mouth ones on its right
LABEL_DZ = 0.019  # label above the first row
LABEL_SCALE = 0.011
# Ojos, Pupilas and Cejas split into: both sides on top, then right and left. Seen from the front
# the character's right is on the viewer's left (-X), so Derecha goes left.
SIDED = ("Ojos", "Pupilas", "Cejas")
SIDES = (("", "Ambos"), ("R", "Derecha"), ("L", "Izquierda"))
SIDE_COLS = 3
SIDE_GAP = 2 * DX  # between the Derecha and Izquierda blocks
SUB_DZ = 0.02  # sub-label above its rows
SUB_SCALE = 0.007
FRAME_PAD = 0.006  # margin of each frame around what it holds
PLAIN_DROP = 0.012  # sections without sub-groups: sliders lowered so their frame clears the title
SLIDER_HALF_W, SLIDER_HALF_H, SLIDER_TRAVEL = 0.004, 0.009, 0.0101  # Gacha's slider shape at scale 0.009


def face_collection(rig, name, row):
    """Bone collection inside "Face" (hiding Face hides all), with a button row in Rigify's panel."""
    face = rig.data.collections_all.get("Face") or rig.data.collections.new("Face")
    coll = rig.data.collections_all.get(f"Cara: {name}") or rig.data.collections.new(f"Cara: {name}", parent=face)
    if hasattr(coll, "rigify_ui_row"):  # only while Rigify is enabled
        coll.rigify_ui_row, coll.rigify_ui_title = row, name
    return coll


def section_of(key):
    k = re.sub(r"^(el_|eb_|mth_)?(mph\d+_)?", "", key.lower())
    if PHONEMES.fullmatch(k):
        return "Fonemas"
    return next((name for name, pat in SECTIONS if re.search(pat, k)), "Cabeza y otros")


def side_of(key):
    """'L', 'R' or '' (both). Case matters: an upper-case L/R ending marks the side (biyanL,
    B_close_L), while eyeball_small or eye_L / look_left (both pupils looking left) are both."""
    k = re.sub(r"^(EL_|EB_|Mth_)?(mph\d+_)?", "", key, flags=re.I)
    if re.fullmatch(r"(?i)(eye|look)_(l|r|left|right)", k):
        return ""
    m = re.search(r"(?<![A-Z])([LR])$", k)
    return m.group(1) if m else ""


def section_layout(name, bones, keys):
    """({slider: (dx, dz)}, [(sub-label, dx, dz)], width, [(sub-label or None, sliders)]) from the
    section's top-left corner; the last item lists the blocks that get an inner frame."""
    groups = {s: [] for s, _ in SIDES}
    for b in bones:
        groups[side_of(keys[b][1]) if name in SIDED else ""].append(b)
    if not (groups["L"] or groups["R"]):  # one plain grid
        pos = {b: ((i % COLS) * DX, -PLAIN_DROP - (i // COLS) * DY) for i, b in enumerate(bones)}
        return pos, [], (min(len(bones), COLS) - 1) * DX, [(None, bones)]
    side_w = (SIDE_COLS - 1) * DX
    width = 2 * side_w + SIDE_GAP
    pos, subs, z = {}, [], 0.0
    both = groups[""]
    if both:
        grid_w = (min(len(both), COLS) - 1) * DX
        subs.append(("Ambos", width / 2, z))
        for i, b in enumerate(both):
            pos[b] = ((width - grid_w) / 2 + (i % COLS) * DX, z - SUB_DZ - (i // COLS) * DY)
        z -= SUB_DZ + ((len(both) - 1) // COLS + 1) * DY
    for (side, label), x0 in zip(SIDES[1:], (0.0, side_w + SIDE_GAP)):
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


def slider_keys(mesh):
    """{slider bone: (first key index, key name)} from the shape-key drivers Gacha made."""
    out = {}
    sk = mesh.data.shape_keys
    if not (sk and sk.animation_data):
        return out
    index = {k.name: i for i, k in enumerate(sk.key_blocks)}
    for d in sk.animation_data.drivers:
        m = re.fullmatch(r'key_blocks\["(.+)"\]\.value', d.data_path)
        bone = next((v.targets[0].bone_target for v in d.driver.variables if v.targets[0].bone_target.startswith("CTRL-")), None)
        if m and bone and m.group(1) in index:
            out[bone] = min(out.get(bone, (1e9, "")), (index[m.group(1)], m.group(1)))
    return out


def arrange_face(context, rig, mesh):
    """Move Gacha's face sliders into labelled sections and give each section a bone collection
    (inside "Face"). Sliders only move, so their drivers (local Z) keep working."""
    keys = slider_keys(mesh)
    if not keys:
        return {}
    groups = {}
    for bone, (i, key) in sorted(keys.items(), key=lambda kv: kv[1]):
        groups.setdefault(section_of(key), []).append(bone)
    layouts = {name: section_layout(name, bones, keys) for name, bones in groups.items()}
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
    old = [b for b in eb if b.name.startswith(("LABEL-", "FRAME-ST"))]
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

    def slider_rect(e):  # handle at rest plus its travel up
        h = e.head
        return h.x - SLIDER_HALF_W, h.z - SLIDER_HALF_H, h.x + SLIDER_HALF_W, h.z + SLIDER_TRAVEL + SLIDER_HALF_H

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
        rects = [label_rect(sub_bone[name], name, LABEL_SCALE)]
        for sub, bones in blocks:  # inner frame per sub-group (or around the whole grid)
            inner = [slider_rect(eb[b]) for b in bones]
            if sub:
                inner.append(label_rect(sub_bone[sub], sub, SUB_SCALE))
            rect = union(inner, FRAME_PAD)
            add_frame(f"{name} {sub or ''}".strip(), rect, coll)
            rects.append(rect)
        side_rects["izquierda" if name in left else "derecha"].append(union(rects, 0))
    for side, rects in side_rects.items():  # outer frame per side of the face
        if rects:
            add_frame(side, union(rects, FRAME_PAD), face_coll)
    bpy.ops.object.mode_set(mode="OBJECT")
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
    return {k: len(v) for k, v in groups.items()}


def frame_widget():
    """Unit square in the XZ plane, centred, scaled per frame."""
    return shading._mesh_obj("WGT-ST_frame", [(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)], None, None, None)


# ---------- gaze ----------
GAZE = "Mirada"
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
    ellipse = [(0.06 * v[0] / 0.03, 0, 0.025 * v[2] / 0.03) for v in shading._circle(0.03)]
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
        c.name, c.target, c.subtarget, c.track_axis = "ST Mirada", rig, f"{GAZE}.{s}", "TRACK_Y"
    return True
