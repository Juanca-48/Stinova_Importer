# SPDX-License-Identifier: GPL-3.0-or-later
"""Skirt collision: a Geometry Nodes modifier, right after the Armature, pushes the skirt's vertices out of the
thighs. Each thigh is a capsule between two empties bone-parented to ORG-thigh (hip and knee); a third, on
ORG-spine, marks where the knee hangs at rest. The cloth in a leg's way first turns with it around the hip; then a
vertex still inside a capsule goes to its surface, leaning towards the side the leg swung to (over the thigh, not
under it). The result is blurred over the mesh so the cloth around follows. The skirt is what the game's bone chains hanging from the hips move (skirt_*, but also
Kanami's pendent_* panels): their weights, summed, are the "ST Skirt" group.
shortcut: no cloth simulation: deep poses can still clip a little, and the cloth doesn't fold. Revisit if needed."""
import bpy
from mathutils import Matrix
from . import shading
from .shading import node, sock

MOD = "ST Skirt Push"
GROUP = "ST Skirt"  # vertex group: how much each vertex is skirt
VERSION = 11  # 2 = each vertex pushed no further than it stood at rest; 3 = the cloth in the way turns with the leg;
#   4 = the rest limit only while the leg is still, exact swing angle; 5 = cloth lies on the thigh, hangs from the knee;
#   6 = follow grows down from above the hip, cloth turned by a share of the swing (no creases); 7 = from higher up;
#   9 = ribbons (long chains) swing out with the leg; 10 = and then droop; 11 = from their middle
REST = "ST Skirt Rest {}"  # point attribute: distance to each thigh at rest
START = 0.2  # the capsule starts this far down the thigh: above, it is the hip, inside the skirt at rest
SMOOTH = 6  # blur iterations of the push
DEPTH = (-0.4, 0.3)  # the follow grows from this far above the hip joint to this far below (x thigh length)
RIBBON = "ST Skirt Ribbon"  # point attribute: how much each vertex is a long, thin chain (a ribbon, a long tail)
RIBBON_LONG = 1.3  # a chain longer than this many thighs is a ribbon: it swings out with the leg
RIBBON_MIDDLE = "ST Skirt Ribbon Middle"  # point attribute: a ribbon's middle, as a distance from the hip


def _vm(nt, op, a, b, x, y):
    n = node(nt, "ShaderNodeVectorMath", x, y, operation=op)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        sock_in = n.inputs["Scale"] if (op == "SCALE" and i == 1) else n.inputs[i]
        if isinstance(v, (int, float)):
            sock_in.default_value = v
        else:
            nt.links.new(v, sock_in)
    return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH") else "Vector"]


def _map(nt, value, a, b, x, y):
    """0 at `a`, 1 at `b`, smoothly, clamped."""
    n = node(nt, "ShaderNodeMapRange", x, y, interpolation_type="SMOOTHSTEP", clamp=True)
    nt.links.new(value, n.inputs["Value"])
    n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = a, b
    return n.outputs["Result"]


def _leg_group():
    ng, built = shading.shared_group("ST Skirt Leg", "GeometryNodeTree", VERSION)
    if built:
        return ng
    for name, typ in (("Position", "NodeSocketVector"), ("Hip", "NodeSocketVector"), ("Knee", "NodeSocketVector"),
                      ("Rest Knee", "NodeSocketVector"), ("Radius", "NodeSocketFloat"), ("Rest Distance", "NodeSocketFloat"),
                      ("Ribbon", "NodeSocketFloat"), ("Ribbon Middle", "NodeSocketFloat")):
        sock(ng, name, "INPUT", typ)
    sock(ng, "Offset", "OUTPUT", "NodeSocketVector")
    gi, go = node(ng, "NodeGroupInput", -2600, 0), node(ng, "NodeGroupOutput", 1200, 0)
    P0, H, K, RK = (gi.outputs[k] for k in ("Position", "Hip", "Knee", "Rest Knee"))
    HK = _vm(ng, "SUBTRACT", K, H, -2400, 200)
    D = _vm(ng, "NORMALIZE", HK, None, -2250, 200)
    Dr = _vm(ng, "NORMALIZE", _vm(ng, "SUBTRACT", RK, H, -2400, -400), None, -2250, -400)
    cos_swing = _vm(ng, "DOT_PRODUCT", D, Dr, -2100, -300)
    # the side the leg swung to: across the thigh at rest, towards where it went
    lead = _vm(ng, "SUBTRACT", D, _vm(ng, "SCALE", Dr, cos_swing, -1950, -350), -1800, -350)
    S = _vm(ng, "NORMALIZE", lead, None, -1650, -350)

    # 1. the cloth in the leg's way goes with it: more the closer it hangs to the thigh and the more it lies on the
    #    side the leg went to. Up to the knee's distance from the hip it turns with the thigh (lying on it); what
    #    is longer hangs from there, down the body (where the knee hangs at rest). A push alone only moves what is
    #    inside the thigh: past ~30 deg the leg had gone through the cloth, which ended up behind it.
    u = _vm(ng, "SUBTRACT", P0, H, -2100, 600)
    ulen = _vm(ng, "LENGTH", u, None, -1950, 750)
    udir = _vm(ng, "NORMALIZE", u, None, -1950, 600)
    # near: how close to the leg's line (at rest) it hangs, measured across it: works above the joint too
    off_axis = _vm(ng, "SUBTRACT", u, _vm(ng, "SCALE", Dr, _vm(ng, "DOT_PRODUCT", u, Dr, -1950, 450), -1800, 450), -1650, 450)
    near = _map(ng, shading.math(ng, "DIVIDE", _vm(ng, "LENGTH", off_axis, None, -1500, 600), _vm(ng, "LENGTH", HK, None, -1650, 700), -1350, 600), 0.6, 0.25, -1200, 600)
    across = _vm(ng, "NORMALIZE", off_axis, None, -1500, 450)
    ahead = _map(ng, _vm(ng, "DOT_PRODUCT", across, S, -1350, 450), -0.3, 0.4, -1200, 450)
    # atan2, not acos: near 0 deg acos turned a still leg by a hair, millimetres at the hem
    swing = shading.math(ng, "ARCTAN2", _vm(ng, "LENGTH", _vm(ng, "CROSS_PRODUCT", Dr, D, -2100, -150), None, -1950, -150), cos_swing, -1800, -200)
    # a dead zone of 3 deg: the rig's rest pose isn't exactly the rest position (the IK leg sits a hair off)
    moving = _map(ng, swing, 0.05, 0.12, -1650, -200)
    thigh_len = _vm(ng, "LENGTH", HK, None, -2250, 50)
    # how far below the hip joint, along the leg at rest: the waist above barely moves, and the follow grows
    # gradually down the cloth (from a little above the joint, so some waist goes along: no crease at the hip)
    depth = _map(ng, shading.math(ng, "DIVIDE", _vm(ng, "DOT_PRODUCT", u, Dr, -1950, 900), thigh_len, -1800, 900), DEPTH[0], DEPTH[1], -1650, 900)
    side_move = shading.math(ng, "MULTIPLY", shading.math(ng, "MULTIPLY", moving, depth, -1200, 750), ahead, -1100, 750)
    # a ribbon goes along even hanging off the leg's line: long and light, it swings out with it
    ribbon = gi.outputs["Ribbon"]
    follow = shading.math(ng, "MAXIMUM", shading.math(ng, "MULTIPLY", near, side_move, -1050, 550),
                          shading.math(ng, "MULTIPLY", side_move, shading.math(ng, "MULTIPLY", ribbon, 0.9, -1200, 850), -1050, 800), -950, 550)
    # turned by a share of the leg's swing, not mixed with where it was: mixing shortened the cloth (creases)
    rot = node(ng, "ShaderNodeVectorRotate", -850, 400, rotation_type="AXIS_ANGLE")
    ng.links.new(udir, rot.inputs["Vector"])
    ng.links.new(_vm(ng, "CROSS_PRODUCT", Dr, D, -1350, 250), rot.inputs["Axis"])
    ng.links.new(shading.math(ng, "MULTIPLY", swing, follow, -1000, 300), rot.inputs["Angle"])
    # up to the knee's distance from the hip it lies on the thigh; past it, it hangs. A ribbon goes along the leg
    # down to its middle and droops from there
    bend = shading.math(ng, "ADD", thigh_len, shading.math(ng, "MULTIPLY", ribbon, shading.math(
        ng, "SUBTRACT", gi.outputs["Ribbon Middle"], thigh_len, -1200, 100), -1100, 100), -1000, 100)
    on_thigh = shading.math(ng, "MINIMUM", ulen, bend, -900, 150)
    hang = shading.math(ng, "MAXIMUM", shading.math(ng, "SUBTRACT", ulen, bend, -900, 50), 0.0, -800, 50)
    # what hangs goes down the body as much as it follows, else along its own (turned) direction
    fall = node(ng, "ShaderNodeMix", -700, 250, data_type="VECTOR")
    ng.links.new(follow, fall.inputs["Factor"])
    ng.links.new(rot.outputs[0], fall.inputs[4])
    ng.links.new(Dr, fall.inputs[5])
    P = _vm(ng, "ADD", _vm(ng, "ADD", H, _vm(ng, "SCALE", rot.outputs[0], on_thigh, -550, 400), -400, 400),
            _vm(ng, "SCALE", _vm(ng, "NORMALIZE", fall.outputs[1], None, -550, 250), hang, -400, 250), -250, 350)

    # 2. what is still inside the thigh goes to its surface, leaning to the side the leg went to (over it, not
    #    under). Cloth that hugs the thigh at rest keeps that distance: pushed no further than it stood.
    # (only while the leg is about still: once it moves, cloth turned halfway must get out of it entirely)
    still = _map(ng, swing, 0.26, 0.0, -750, -700)  # 1 at rest, 0 from 15 deg
    R = shading.math(ng, "SUBTRACT", gi.outputs["Radius"], shading.math(ng, "MULTIPLY", still, shading.math(ng, "MAXIMUM", shading.math(
        ng, "SUBTRACT", gi.outputs["Radius"], gi.outputs["Rest Distance"], -900, -650), 0.0, -750, -650), -600, -650), -450, -600)
    A = _vm(ng, "ADD", H, _vm(ng, "SCALE", HK, START, -700, 200), -600, 200)
    AB = _vm(ng, "SUBTRACT", K, A, -500, 200)
    t = shading.math(ng, "DIVIDE", _vm(ng, "DOT_PRODUCT", _vm(ng, "SUBTRACT", P, A, -500, 0), AB, -400, 0),
                     _vm(ng, "DOT_PRODUCT", AB, AB, -400, 100), -300, 0)
    ng.nodes[-1].use_clamp = True
    C = _vm(ng, "ADD", A, _vm(ng, "SCALE", AB, t, -200, 100), -100, 100)
    v = _vm(ng, "SUBTRACT", P, C, 0, 0)
    radial = _vm(ng, "NORMALIZE", v, None, 100, -100)
    want = _vm(ng, "NORMALIZE", _vm(ng, "ADD", radial, _vm(ng, "SCALE", lead, 2.0, 100, -350), 250, -200), None, 400, -200)
    target = _vm(ng, "ADD", C, _vm(ng, "SCALE", want, R, 550, -200), 700, -100)
    inside = shading.math(ng, "LESS_THAN", _vm(ng, "LENGTH", v, None, 100, 0), R, 250, 100)
    pushed = _vm(ng, "ADD", P, _vm(ng, "SCALE", _vm(ng, "SUBTRACT", target, P, 800, -100), inside, 900, 0), 1000, 0)
    ng.links.new(_vm(ng, "SUBTRACT", pushed, P0, 1100, 0), go.inputs["Offset"])
    return ng


def push_group():
    ng, built = shading.shared_group(MOD, "GeometryNodeTree", VERSION)
    if built:
        return ng
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    for side in "LR":
        for key in ("Hip", "Knee", "Rest Knee"):
            sock(ng, f"{key} {side}", "INPUT", "NodeSocketObject")
        sock(ng, f"Radius {side}", "INPUT", "NodeSocketFloat", 0.1)
    sock(ng, "Enabled", "INPUT", "NodeSocketBool", True)  # animatable, viewport and render alike
    s = sock(ng, "Smoothing", "INPUT", "NodeSocketInt", SMOOTH)
    s.min_value, s.max_value = 0, 20
    gi, go = node(ng, "NodeGroupInput", -1200, 0), node(ng, "NodeGroupOutput", 1000, 0)
    pos = node(ng, "GeometryNodeInputPosition", -1000, 400).outputs[0]
    leg = _leg_group()
    total = None
    for j, side in enumerate("LR"):
        g = node(ng, "GeometryNodeGroup", -500, 300 - 450 * j, node_tree=leg)
        ng.links.new(pos, g.inputs["Position"])
        for k, key in enumerate(("Hip", "Knee", "Rest Knee")):
            oi = node(ng, "GeometryNodeObjectInfo", -800, 300 - 450 * j - 130 * k, transform_space="RELATIVE")
            ng.links.new(gi.outputs[f"{key} {side}"], oi.inputs["Object"])
            ng.links.new(oi.outputs["Location"], g.inputs[key])
        ng.links.new(gi.outputs[f"Radius {side}"], g.inputs["Radius"])
        rest = node(ng, "GeometryNodeInputNamedAttribute", -800, -50 - 450 * j, data_type="FLOAT")
        rest.inputs["Name"].default_value = REST.format(side)
        ng.links.new(rest.outputs["Attribute"], g.inputs["Rest Distance"])
        rib = node(ng, "GeometryNodeInputNamedAttribute", -800, -150 - 450 * j, data_type="FLOAT")
        rib.inputs["Name"].default_value = RIBBON
        ng.links.new(rib.outputs["Attribute"], g.inputs["Ribbon"])
        mid = node(ng, "GeometryNodeInputNamedAttribute", -800, -250 - 450 * j, data_type="FLOAT")
        mid.inputs["Name"].default_value = RIBBON_MIDDLE
        ng.links.new(mid.outputs["Attribute"], g.inputs["Ribbon Middle"])
        total = g.outputs[0] if total is None else _vm(ng, "ADD", total, g.outputs[0], -250, 0)
    w = node(ng, "GeometryNodeInputNamedAttribute", -500, -650, data_type="FLOAT")
    w.inputs["Name"].default_value = GROUP
    weight = w.outputs["Attribute"]
    blur = node(ng, "GeometryNodeBlurAttribute", 100, 0, data_type="FLOAT_VECTOR")
    ng.links.new(_vm(ng, "SCALE", total, weight, -100, 0), blur.inputs["Value"])
    ng.links.new(gi.outputs["Smoothing"], blur.inputs["Iterations"])
    ng.links.new(weight, blur.inputs["Weight"])
    sel = node(ng, "FunctionNodeCompare", 400, 200, data_type="FLOAT", operation="GREATER_THAN")
    ng.links.new(weight, sel.inputs[0])
    on = node(ng, "FunctionNodeBooleanMath", 500, 250, operation="AND")
    ng.links.new(sel.outputs[0], on.inputs[0])
    ng.links.new(gi.outputs["Enabled"], on.inputs[1])
    sp = node(ng, "GeometryNodeSetPosition", 600, 0)
    ng.links.new(gi.outputs["Geometry"], sp.inputs["Geometry"])
    ng.links.new(on.outputs[0], sp.inputs["Selection"])  # only the skirt is computed
    ng.links.new(_vm(ng, "SCALE", blur.outputs[0], weight, 400, -100), sp.inputs["Offset"])
    ng.links.new(sp.outputs[0], go.inputs[0])
    return ng


def _dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def add(context, rig, obj):
    """Skirt collision for `obj`, rigged by `rig`. Returns False when it has no skirt bones."""
    hips = rig.data.bones.get("ORG-spine")
    thigh = {s: rig.data.bones.get(f"ORG-thigh.{s}") for s in "LR"}
    if not hips or not all(thigh.values()):
        return False
    names, ribbons = set(), {}  # ribbons: bone -> its chain's middle, as a distance from the hip joint
    for c in hips.children:
        if c.use_deform and not c.name.startswith("DEF-"):  # the game's own chains, not Rigify's
            chain = [c] + list(c.children_recursive)
            names |= {b.name for b in chain}
            length = sum(b.length for b in chain)
            if length > RIBBON_LONG * thigh["L"].length:
                hip = min((thigh[s].head_local - c.head_local).length for s in "LR")
                ribbons.update({b.name: hip + length / 2 for b in chain})
    groups = {g.index: g.name for g in obj.vertex_groups}
    if not names:
        return False
    vg = obj.vertex_groups.get(GROUP) or obj.vertex_groups.new(name=GROUP)
    skirt = []
    for v in obj.data.vertices:
        w = sum(e.weight for e in v.groups if groups.get(e.group) in names)
        if w > 0.01:
            vg.add([v.index], min(1.0, w), "REPLACE")
            skirt.append(v.index)
    if not skirt:
        return False
    share, middle = [], []
    for v in obj.data.vertices:
        w = [(e.weight, ribbons[groups[e.group]]) for e in v.groups if groups.get(e.group) in ribbons]
        total = sum(x for x, _ in w)
        share.append(min(1.0, total))
        middle.append(sum(x * m for x, m in w) / total if total else 0.0)
    for name, values in ((RIBBON, share), (RIBBON_MIDDLE, middle)):
        att = obj.data.attributes.get(name) or obj.data.attributes.new(name, "FLOAT", "POINT")
        att.data.foreach_set("value", values)

    # radius: the thigh's own (90 % of its vertices are closer to the bone), measured in the rest position whatever
    # the current pose. The skirt can touch it at rest: it moves a few millimetres there, but a thinner capsule
    # left the cloth inside the leg.
    was = rig.data.pose_position
    rig.data.pose_position = "REST"
    old = obj.modifiers.get(MOD)
    if old:  # set up again: measure without its own push
        old.show_viewport = False
    context.view_layer.update()
    ev = obj.evaluated_get(context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    co = [ev.matrix_world @ me.vertices[i].co for i in range(len(obj.data.vertices))]
    ev.to_mesh_clear()
    W = rig.matrix_world
    radius = {}
    for s, b in thigh.items():
        pb = rig.pose.bones[b.name]
        a, k = W @ pb.head, W @ pb.tail
        own = {i for i, n in groups.items() if n.startswith(f"DEF-thigh.{s}")}
        d = sorted(_dist(co[v.index], a, k) for v in obj.data.vertices if sum(e.weight for e in v.groups if e.group in own) > 0.6)
        r = d[int(len(d) * 0.9)] + 0.012 if d else 0.09
        radius[s] = r
        att = obj.data.attributes.get(REST.format(s)) or obj.data.attributes.new(REST.format(s), "FLOAT", "POINT")
        rest = [1.0] * len(obj.data.vertices)  # far: no limit
        for i in skirt:
            rest[i] = max(0.0, _dist(co[i], a.lerp(k, START), k) - 0.001)
        att.data.foreach_set("value", rest)

    coll = rig.users_collection[0] if rig.users_collection else context.scene.collection
    mod = old or obj.modifiers.new(MOD, "NODES")
    mod.show_viewport = True
    mod.node_group = push_group()
    for s, b in thigh.items():
        pb = rig.pose.bones[b.name]
        for key, bone, at in (("Hip", b.name, pb.head), ("Knee", b.name, pb.tail), ("Rest Knee", "ORG-spine", pb.tail)):
            name = f"ST Skirt {key} {s} {obj.name}"
            e = bpy.data.objects.get(name) or bpy.data.objects.new(name, None)
            if e.name not in coll.objects:
                coll.objects.link(e)
            e.empty_display_size = 0.03
            e.parent, e.parent_type, e.parent_bone = rig, "BONE", bone
            context.view_layer.update()
            e.matrix_world = rig.matrix_world @ Matrix.Translation(at)
            e.hide_render = e.hide_select = True
            e.hide_set(True)
            shading.mod_input(mod, f"{key} {s}").value = e
        shading.mod_input(mod, f"Radius {s}").value = radius[s]
    rig.data.pose_position = was  # the empties were placed at rest too
    context.view_layer.update()
    arm_i = next((i for i, m in enumerate(obj.modifiers) if m.type == "ARMATURE"), None)
    if arm_i is not None:
        obj.modifiers.move(obj.modifiers.find(MOD), arm_i + 1)

    return True


def modifier(rig):
    """The skirt collision modifier of the character rigged by `rig`, if it has one."""
    for o in rig.children_recursive:
        if o.type == "MESH" and MOD in o.modifiers:
            return o.modifiers[MOD]
    return None
