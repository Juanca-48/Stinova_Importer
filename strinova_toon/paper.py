"""Paper version (Mesh2D) of a character, driven by the 3D character's rig, plus a switch between them.

Strinova's paper model shares the 3D skeleton (Bip001-, hair_*, dress_*), so its vertex groups are
renamed to the rig's deform bones the way Gacha Setup's NTE rigger renamed the 3D mesh, and the
same rig moves both. The game swaps them in a single frame, hidden by the animation; here the
rig's "st_paper" property does the same (keyframe it: a bool keys with constant interpolation).
"""
import bpy, os, re
from . import common
from .common import iface_, tip_, rpt_
from mathutils import Vector

PAPER_PROP = "st_paper"
BODY = {  # Bip001-<x> -> Rigify deform bone (Gacha Setup's NTE table)
    "Pelvis": "DEF-spine", "Spine": "DEF-spine.001", "Spine1": "DEF-spine.002", "Spine2": "DEF-spine.003",
    "Neck": "DEF-spine.004", "Head": "DEF-spine.006",
}
LIMBS = {"Thigh": "thigh", "Calf": "shin", "Foot": "foot", "Toe0": "toe", "Clavicle": "shoulder",
         "UpperArm": "upper_arm", "Forearm": "forearm", "Hand": "hand"}
FINGERS = ("thumb", "f_index", "f_middle", "f_ring", "f_pinky")


def is_paper_path(path):
    return f"{os.sep}Mesh2D{os.sep}" in os.path.normpath(path)


def rig_bone(name, rig):
    """Rig deform bone for a vertex group of the raw skeleton, or None."""
    b = rig.data.bones.get(name)
    if b and b.use_deform:
        return name  # hair_*, dress_*, Bip001-L-ForeTwist... keep their names in the rig
    m = re.fullmatch(r"Bip001-(\w+)", name)
    if m and m.group(1) in BODY:
        return BODY[m.group(1)]
    m = re.fullmatch(r"Bip001-([LR])-?(\w+)", name)
    if not m:
        return None
    side, part = m.groups()
    if part in LIMBS:
        return f"DEF-{LIMBS[part]}.{side}"
    if part == "UpArmTwist":  # the paper model weights its upper arm to the twist bone
        return f"DEF-upper_arm.{side}"
    f = re.fullmatch(r"Finger(\d)(\d?)", part)
    if f:  # FingerN, FingerN1, FingerN2 -> .01 .02 .03 (3-bone chains, like Strinova's 3D hands)
        return f"DEF-{FINGERS[int(f.group(1))]}.0{int(f.group(2) or 0) + 1}.{side}"
    return None


def merge_group(obj, src, dst):
    s = obj.vertex_groups[src]
    d = obj.vertex_groups.get(dst)
    if not d:
        s.name = dst
        return
    for v in obj.data.vertices:
        w = next((g.weight for g in v.groups if g.group == s.index), 0.0)
        if w:
            d.add([v.index], w, "ADD")
    obj.vertex_groups.remove(s)


def attach(context, paper, host):
    """Bind the paper mesh to the host (3D) character's rig, sharing its lighting objects."""
    rig = host.find_armature()
    raw = paper.find_armature()
    unmapped = []
    for g in list(paper.vertex_groups):
        target = rig_bone(g.name, rig)
        # bones the 3D skeleton lacks (e.g. Eika's sleeve ribbon tips cloth_UpperArm_*_04): follow the
        # nearest parent the rig has, or those vertices stay pinned in place
        b = raw.data.bones.get(g.name) if raw else None
        while (target is None or target not in rig.data.bones) and b and b.parent:
            b = b.parent
            target = rig_bone(b.name, rig)
        if target is None or target not in rig.data.bones:
            unmapped.append(g.name)
        elif target != g.name:
            merge_group(paper, g.name, target)
    rel = raw.matrix_world.inverted() @ paper.matrix_world if raw else paper.matrix_world.copy()
    paper.parent, paper.parent_type = rig, "OBJECT"
    paper.matrix_parent_inverse.identity()
    paper.matrix_world = rig.matrix_world @ rel
    for mod in paper.modifiers:
        if mod.type == "ARMATURE":
            mod.object = rig
    if raw and raw != rig:
        bpy.data.objects.remove(raw)
    paper[PAPER_PROP] = True
    # same sun, head empties and lighting panel as the 3D model (shading reuses these pointers)
    for k in ("st_light", "st_head_origin", "st_head_forward", "st_head_up"):
        if isinstance(host.get(k), bpy.types.Object):
            paper[k] = host[k]
    return unmapped  # the importer adds the switch after the shading (its modifiers go last)


HIDE = "ST Ocultar"


def hide_group():
    """Geometry Nodes group that deletes everything: the switch turns it on to hide a mesh."""
    ng = bpy.data.node_groups.get(HIDE)
    if ng:
        return ng
    ng = bpy.data.node_groups.new(HIDE, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    dl = ng.nodes.new("GeometryNodeDeleteGeometry")
    gi.location, dl.location, go.location = (-300, 0), (0, 0), (300, 0)
    ng.links.new(gi.outputs[0], dl.inputs["Geometry"])
    ng.links.new(dl.outputs[0], go.inputs[0])
    return ng  # Delete Geometry's Selection defaults to true: all of it


def ensure_switch(rig):
    """rig["st_paper"]: off = 3D model, on = paper. Each mesh ends with an "ST Ocultar" modifier
    that the property switches on to hide it."""
    for o in bpy.data.objects:
        if o.type != "MESH" or o.find_armature() != rig:
            continue
        mod = o.modifiers.get(HIDE) or o.modifiers.new(HIDE, "NODES")
        mod.node_group = hide_group()
        o.modifiers.move(o.modifiers.find(HIDE), len(o.modifiers) - 1)  # last: hides the outline too
        common.drive_modifier(mod, rig, PAPER_PROP, "1 - v" if o.get(PAPER_PROP) else "v", False,
                              tip_("Shows the paper version instead of the 3D model"))


def find_host(coll):
    """The rigged 3D character mesh in `coll` (a character collection), if any."""
    for o in coll.all_objects if coll else ():
        arm = o.find_armature() if o.type == "MESH" else None
        if arm and o.get("st_light") and not o.get(PAPER_PROP) and "DEF-spine.006" in arm.data.bones:
            return o
    return None
