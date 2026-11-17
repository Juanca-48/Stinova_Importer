"""Accessory bones: masks and hats that follow the head but can be moved, or scaled to 0 to take
them off. Bones the model already has (mask_bone, maskA_L_bone...) and Eika's masks get a control at
import. Most hats share the head's or a hair bone's weights, so they get none."""
import bpy, re
from mathutils import Vector
from . import shading, common
from .common import iface_, tip_, rpt_

COLL = "Accesorios"
PREFIX = "ACC-"
OWN_BONE = re.compile(r"(?i)mask")  # accessory bones found in Strinova skeletons
COLOR = (1.0, 0.75, 0.1)


MASK_SIZE = 0.025  # half width of the widget (m)
MASK_FRONT = 0.03  # in front of the piece


def mask_widget():
    """Inverted triangle with two circles (eyes), in the XZ plane facing -Y, about 2 x 2 units."""
    tri = [(-1.0, 0, 0.7), (1.0, 0, 0.7), (0.0, 0, -1.0)]
    verts, edges = list(tri), [(0, 1), (1, 2), (2, 0)]
    for cx in (-0.42, 0.42):
        start = len(verts)
        verts += [(cx + x, 0, 0.28 + z) for x, _, z in shading._circle(0.24, 16)]
        edges += [(start + i, start + (i + 1) % 16) for i in range(16)]
    return shading._mesh_obj("WGT-ST_accessory_mask", verts, None, None, None, edges=edges)


def make_control(rig, name, points):
    """Bone `name` into the visible Accesorios collection, drawn as a small mask in front of the
    piece at `points` (world). The widget is turned out of the bone's own axes to face the front."""
    coll = rig.data.collections_all.get(COLL) or rig.data.collections.new(COLL)
    b = rig.data.bones[name]
    for c in list(b.collections):
        c.unassign(b)
    coll.assign(b)
    inv = rig.matrix_world.inverted()
    pts = [inv @ p for p in points]  # rig space: the character faces -Y
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    front = Vector(((lo.x + hi.x) / 2, lo.y - MASK_FRONT, (lo.z + hi.z) / 2))
    rot = b.matrix_local.to_3x3().normalized().inverted()
    pb = rig.pose.bones[name]
    pb.custom_shape = mask_widget()
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_rotation_euler = rot.to_euler()
    pb.custom_shape_translation = rot @ (front - b.head_local)
    pb.custom_shape_scale_xyz = (MASK_SIZE,) * 3
    common.paint(rig, name, COLOR, (1.0, 0.9, 0.5))


def piece(mesh, match, minimum=0.5):
    """Vertices whose weights in the groups `match` accepts add up to `minimum` or more."""
    groups = {g.index for g in mesh.vertex_groups if match(g.name)}
    return [v.index for v in mesh.data.vertices
            if groups and sum(e.weight for e in v.groups if e.group in groups) >= minimum]


def world_points(mesh, idx):
    return [mesh.matrix_world @ mesh.data.vertices[i].co for i in idx]


SHOW = "st_show_"  # rig property per accessory (st_show_<bone>): off hides the piece
HIDE = "ST Ocultar grupo"


def hide_group_nodes():
    """Geometry Nodes group deleting the vertices of the vertex group named in its "Grupo" input."""
    ng = bpy.data.node_groups.get(HIDE)
    if ng:
        return ng
    ng = bpy.data.node_groups.new(HIDE, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Grupo", in_out="INPUT", socket_type="NodeSocketString")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    attr = n.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT"
    cmp = n.new("FunctionNodeCompare")
    cmp.data_type, cmp.operation = "FLOAT", "GREATER_THAN"
    cmp.inputs["B"].default_value = 0.5
    dl = n.new("GeometryNodeDeleteGeometry")
    for i, node in enumerate((gi, attr, cmp, dl, go)):
        node.location = (i * 220 - 440, 0)
    ng.links.new(gi.outputs["Grupo"], attr.inputs["Name"])
    ng.links.new(attr.outputs["Attribute"], cmp.inputs["A"])
    ng.links.new(cmp.outputs["Result"], dl.inputs["Selection"])
    ng.links.new(gi.outputs["Geometry"], dl.inputs["Geometry"])
    ng.links.new(dl.outputs[0], go.inputs[0])
    return ng


def add_toggle(rig, mesh, bone, idx):
    """rig["st_show_<bone>"]: off hides the piece (viewport and render). A modifier right after the
    armature deletes its vertex group, so the outline built from the mesh goes too."""
    prop, vg_name, mod_name = SHOW + bone, f"ST {bone}", f"ST Ocultar {bone}"
    vg = mesh.vertex_groups.get(vg_name) or mesh.vertex_groups.new(name=vg_name)
    vg.add(idx, 1.0, "REPLACE")
    mod = mesh.modifiers.get(mod_name) or mesh.modifiers.new(mod_name, "NODES")
    mod.node_group = hide_group_nodes()
    shading.mod_input(mod, "Grupo").value = vg_name
    arm_i = next((i for i, m in enumerate(mesh.modifiers) if m.type == "ARMATURE"), -1)
    mesh.modifiers.move(mesh.modifiers.find(mod_name), arm_i + 1)
    common.drive_modifier(mod, rig, prop, "1 - v", True, tip_("Shows or hides {} (animatable)").format(bone))  # on = hidden


def add_existing(rig, mesh):
    """Controls and show toggles for the accessory bones the skeleton already has (masks)."""
    done = 0
    for b in rig.data.bones:
        idx = piece(mesh, lambda n, b=b: n == b.name) if OWN_BONE.search(b.name) else []
        if idx:
            make_control(rig, b.name, world_points(mesh, idx))
            add_toggle(rig, mesh, b.name, idx)
            done += 1
    return done


HEADGEAR = {"Aika": "hair_tt"}  # character -> bones of its headgear ("tou tao"): Eika's masks


def add_headgear(context, rig, mesh):
    """Eika's masks hang from hair_tt_* bones. Give them a parent bone, ACC-Mascara (child of the
    head), plus a show toggle. Weights stay as they are, so a chain with physics keeps it."""
    prefix = next((p for c, p in HEADGEAR.items() if c in mesh.name or c in rig.name), None)
    name = PREFIX + "Mascara"
    if not prefix or name in rig.data.bones:
        return False
    idx = piece(mesh, lambda n: n.startswith(prefix))
    roots = [b.name for b in rig.data.bones if b.name.startswith(prefix)
             and not (b.parent and b.parent.name.startswith(prefix))]
    if not idx or not roots:
        return False  # skins with the bone but no mask weighted to it
    points = world_points(mesh, idx)
    center = sum(points, Vector()) / len(points)
    size = max(max(p[k] for p in points) - min(p[k] for p in points) for k in range(3))
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    e = eb.new(name)
    e.head = rig.matrix_world.inverted() @ center
    e.tail = e.head + Vector((0, 0, max(size / 2, 0.03)))
    e.parent = eb[roots[0]].parent
    e.use_deform = False  # moves the mask through its own bones
    for r in roots:
        eb[r].use_connect = False
        eb[r].parent = e
    bpy.ops.object.mode_set(mode="OBJECT")
    make_control(rig, name, points)
    add_toggle(rig, mesh, name, idx)
    return True
