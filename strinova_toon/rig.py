"""Rig: Rigify rig through Gacha Setup's NTE rigger, Strinova-specific fixes on top of it, and the
constraint 'physics' for hair, clothes and chest."""
import bpy, re, math, contextlib
from mathutils import Vector
from .common import target_mesh
from . import shading, face, accessory, skirt
from .common import iface_, tip_, rpt_

# ---------- rig + physics ----------
PHYS_COLLECTIONS = ("Hair", "Clothes")
NOT_PHYSICS = {"SocketADS"}  # gameplay socket Gacha Setup files under Clothes


PHYSICS_PROP = "st_physics"  # on/off toggle: multiplies every inertia influence, live and animatable
INERTIA_PROPS = {  # group: (rig property, default influence, panel label)
    # 20% stiffer than Gacha Setup's 0.7 / 0.4: theirs felt too loose on Strinova's chains
    "Hair": ("st_hair_inertia", 0.56, "Hair inertia"),
    "Bangs": ("st_bangs_inertia", 0.28, "Bangs inertia"),  # bangs sway half as much as the back hair
    "Clothes": ("st_cloth_inertia", 0.32, "Clothes inertia"),
    "Breast": ("st_breast_inertia", 0.2, "Chest inertia"),
}
EYEBALLS = ("eye_l_ball_01", "eye_r_ball_01")
EYE_CHAIN_DIST = 0.025  # m: a physics chain rooted this close to an eyeball's centre lives in the eye


def eye_chains(context, rig):
    """Some skins hang the eye's highlight layer on a short chain inside the eyeball, named like an
    accessory (Eika S211: earring_l_01/02, 1.4 cm from the eye's centre; eyelashes are elsewhere,
    outside the physics). Filed as clothes, it followed the head instead of the eye and got inertia:
    the highlights stayed put when the eyes moved, and wobbled. Hang each such chain from its eyeball
    and take it out of the physics. Run before apply_inertia, which reads the Hair/Clothes collections."""
    bones, colls = rig.data.bones, rig.data.collections_all
    eyes = [n for n in EYEBALLS if n in bones]
    phys = {b.name for c in PHYS_COLLECTIONS if c in colls for b in colls[c].bones}
    roots = {}
    for n in phys:
        b = bones[n]
        if b.parent and b.parent.name in phys:
            continue  # not a chain's first bone
        eye = min(eyes, key=lambda e: (b.head_local - bones[e].head_local).length, default=None)
        if eye and (b.head_local - bones[eye].head_local).length < EYE_CHAIN_DIST:
            roots[n] = eye
    if not roots:
        return []
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for root, eye in roots.items():
        eb[root].use_connect = False
        eb[root].parent = eb[eye]
    bpy.ops.object.mode_set(mode="OBJECT")
    for root, eye in roots.items():
        for b in [bones[root]] + list(bones[root].children_recursive):
            for c in PHYS_COLLECTIONS:
                if c in colls:
                    colls[c].unassign(b)
            for c in bones[eye].collections:  # hidden with the eyeball ("Other")
                c.assign(b)
    return sorted(roots)


def apply_inertia(rig):
    """Gacha Setup style 'physics': each Hair/Clothes chain bone (and Strinova's chest_l/r chains)
    gets a Damped Track towards its own child. That is a dependency cycle on purpose: Blender
    resolves it with the previous evaluation, so strands trail behind the body while animating,
    which reads as inertia. Unlike Gacha's button it only touches those bones (theirs also hit
    Rigify MCH/IK bones on this rig). Trade-off: the result depends on the frames evaluated
    before, so jumping around the timeline or rendering single frames can differ from playback."""
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="OBJECT")
    colls = rig.data.collections_all
    group = {b.name: c for c in PHYS_COLLECTIONS if c in colls for b in colls[c].bones if b.name not in NOT_PHYSICS}
    group.update({b.name: "Breast" for b in rig.data.bones if re.fullmatch(r"chest_[lr]_\d+", b.name)})
    # Bangs / front locks: hair chains whose tip ends in front of the eyes (rig faces -Y). By where
    # the strand ends, not its name or root: Kanami's hair_f_m2 is rooted behind but falls over the face.
    eyes = [b.head_local.y for b in rig.data.bones if "eye" in b.name.lower() and "ball" in b.name.lower()]
    head = rig.data.bones.get("DEF-spine.006")
    face_y = min(eyes) if eyes else (head.head_local.y - 0.05 if head else None)
    if face_y is not None:
        hair = {n for n, g in group.items() if g == "Hair"}
        tip_y = {}
        for n in hair:  # tip of the chain below each bone
            t = rig.data.bones[n]
            while True:
                kids = sorted((c for c in t.children if c.name in hair), key=lambda c: c.name)
                if not kids:
                    break
                t = kids[0]
            tip_y[n] = t.tail_local.y
        for n in hair:
            r = rig.data.bones[n]
            while r.parent and r.parent.name in hair:
                r = r.parent
            if tip_y[r.name] < face_y + 0.01:
                group[n] = "Bangs"
    for c in PHYS_COLLECTIONS:
        if c in colls:
            colls[c].is_visible = False  # keep only the controllers in view; the sliders drive these chains
    for g, (prop, default, label) in INERTIA_PROPS.items():
        if prop not in rig:
            rig[prop] = default
        rig.id_properties_ui(prop).update(min=0.0, max=1.0, description=tip_("{}: how much it lags and drags when animating").format(iface_(label)))
    if PHYSICS_PROP not in rig:
        rig[PHYSICS_PROP] = True
    rig.id_properties_ui(PHYSICS_PROP).update(description=tip_("Turns hair, clothes and chest physics on"))

    # Damped Track aims the bone's Y axis at its child. UEFormat imports Strinova's chain bones
    # pointing elsewhere (not at the child), so tracking would swing every bone ~90 deg at rest.
    # Point each one at its child first (tips continue the chain); heads stay, so the mesh, bound
    # to this same rest pose, does not move.
    kids_of = {n: sorted(ch.name for ch in rig.data.bones[n].children if ch.name in group) for n in group}
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for n in group:
        b = eb[n]
        if kids_of[n]:
            aim = eb[kids_of[n][0]].head - b.head
        elif b.parent and b.parent.name in group:
            aim = (b.head - b.parent.head).normalized() * max(b.length, 0.02)
        else:
            continue
        if aim.length > 1e-4:
            b.tail = b.head + aim
    bpy.ops.object.mode_set(mode="OBJECT")

    chains = 0
    for n, g in group.items():
        kids = kids_of[n]
        if not kids:
            continue  # tip of a chain
        if g == "Breast" and kids_of[kids[0]]:
            continue  # chest: one cycle per side, on the weighted bone; chained cycles made one side jitter
        p = rig.data.bones[n].parent
        chains += not (p and p.name in group)
        c = rig.pose.bones[n].constraints.new("DAMPED_TRACK")
        c.name, c.target, c.subtarget, c.track_axis = "ST Inertia", rig, kids[0], "TRACK_Y"
        drv = c.driver_add("influence").driver
        drv.type, drv.expression = "SCRIPTED", "inercia * activa"  # simple expression: no auto-run needed
        for name, prop in (("inercia", INERTIA_PROPS[g][0]), ("activa", PHYSICS_PROP)):
            v = drv.variables.new()
            v.name, v.type = name, "SINGLE_PROP"
            v.targets[0].id, v.targets[0].data_path = rig, f'["{prop}"]'
    return chains


def target_rig(context):
    ob = context.active_object
    if ob and ob.type == "MESH":
        ob = ob.find_armature()
    return ob if ob and ob.type == "ARMATURE" and "Hair" in ob.data.collections_all else None


def fix_finger_curl(rig):
    """Gacha's NTE rigger rolls each finger so it curls the way it already bends at rest. Strinova's
    T-pose fingers bend slightly up, so the master's scale-curl (driver (1-sy)*pi on the MCH *_drv
    bones) closed them backwards. A positive curl moves the tip towards the bone's local +Z; with
    the palms facing down in the rest pose that must point down, otherwise flip the driver sign."""
    drivers = rig.animation_data.drivers if rig.animation_data else []
    for side in (".L", ".R"):
        for f in ("f_index", "f_middle", "f_ring", "f_pinky", "thumb"):  # thumb: Gacha doesn't mirror it for .R
            b = rig.data.bones.get(f"ORG-{f}.01{side}")
            if not b:
                continue
            backwards = (rig.matrix_world.to_3x3() @ b.matrix_local.to_3x3()).col[2].z > 0
            for d in drivers:
                if d.data_path.startswith(f'pose.bones["MCH-{f}.') and f'_drv{side}"]' in d.data_path:
                    expr = d.driver.expression.lstrip("-")
                    d.driver.expression = f"-{expr}" if backwards else expr  # set, not toggle: safe to rerun


def fix_breasts(context, rig):
    """Rigify's breast.L/R controls move DEF-breast, which no vertex is weighted to: Strinova skins
    the chest to its own chest_l_* / chest_r_* chains, left hanging from the spine. Move the
    breast bones onto each chain (Rigify parks them ~14 cm in front of the body, a bad pivot)
    and hang the chain from ORG-breast, which copies the control."""
    chains = {}
    for b in rig.data.bones:
        m = re.fullmatch(r"chest_([lr])_\d+", b.name)
        if m:
            chains.setdefault(m.group(1).upper(), []).append(b.name)
    sides = [s for s in chains if f"ORG-breast.{s}" in rig.data.bones]
    if not sides:
        return []
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for s in sides:
        names = sorted(chains[s])
        root = next(eb[n] for n in names if not (eb[n].parent and eb[n].parent.name in names))
        tip = eb[names[-1]].tail.copy()
        for n in (f"breast.{s}", f"ORG-breast.{s}", f"DEF-breast.{s}"):
            if n in eb:
                eb[n].head, eb[n].tail = root.head.copy(), tip
        root.use_connect = False
        root.parent = eb[f"ORG-breast.{s}"]
    bpy.ops.object.mode_set(mode="OBJECT")
    return sides


def bend_straight_fingers(context, arm):
    """Some skeletons (Nora) have two-bone fingers whose tip continues its base in a straight line
    (the FBX import extends a leaf bone along its parent). Gacha's NTE rigger takes the fingers' curl
    plane from the index's first two bones and crashes ("Vector must be 2D or 3D") when they are in
    line. Bend each straight tip like the most bent finger of the same hand; at rest the mesh doesn't
    change (only the tip bone's rest direction does)."""
    bones = arm.data.bones
    hands = {b.parent.name for b in bones if re.fullmatch(r"Bip001-[LR]-Finger\d", b.name) and b.parent}
    if not hands:
        return 0
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    n = 0
    for hand in hands:
        pairs = [(b, b.children[0]) for b in eb[hand].children if re.fullmatch(r"Bip001-[LR]-Finger\d", b.name)
                 and len(b.children) == 1 and not b.children[0].children]  # base + tip
        bend = lambda a, t: (a.tail - a.head).normalized().rotation_difference((t.tail - t.head).normalized())
        bent = max((bend(a, t) for a, t in pairs), key=lambda q: q.angle, default=None)
        if not bent or bent.angle < math.radians(1):
            continue
        for a, t in pairs:
            if bend(a, t).angle < math.radians(0.5):
                t.tail = t.head + bent @ (t.tail - t.head)
                n += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    return n


def fix_thumb_axis(context, rig):
    """Gacha's rigger lets Rigify infer the thumb's curl axis from how the thumb bends at rest; on some
    skeletons (Flavia, Eika) that bend points back at the wrist, and closing the thumb folded it
    towards the arm. Roll the whole thumb chain (controls, ORG, DEF, MCH: they share one axis) so a
    curl turns the tip across the palm, to the ring and little fingers' base. Run before
    fix_finger_curl, which picks the curl's sign from these rolls. Only rest frames change: the mesh
    doesn't move."""
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    n = 0
    for s in ("L", "R"):
        t2, hand = eb.get(f"ORG-thumb.02.{s}"), eb.get(f"DEF-hand.{s}")
        index, ring, pinky = (eb.get(f"DEF-f_{f}.01.{s}") for f in ("index", "ring", "pinky"))
        if not (t2 and hand and index and ring and pinky):
            continue
        normal = (index.head - hand.head).cross(pinky.head - hand.head).normalized()
        if normal.z > 0:  # palms face down in the rest pose: the palm side is -Z
            normal.negate()
        target = (ring.head + pinky.head) / 2 + normal * (index.head - pinky.head).length * 0.5
        y = t2.vector.normalized()
        toward = target - t2.tail
        toward -= y * toward.dot(y)
        hinge = y.cross(toward).normalized()  # a positive curl about +X turns +Y towards +Z, the target
        for b in eb:
            if re.search(rf"thumb\.0\d.*\.{s}(\.\d+)?$", b.name):
                yb = b.vector.normalized()
                h = hinge - yb * hinge.dot(yb)
                if h.length > 1e-4:
                    b.align_roll(h.normalized().cross(yb))  # Z = X x Y
                    n += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    return n


KNEE_START_BEND = 1.0  # degrees, see fix_leg_axis


def fix_leg_axis(context, rig):
    """Rigify's IK knee only turns about the shin's X axis. Strinova's legs rest almost straight (Eika:
    knee 1.6 mm off the hip-ankle line), so the inferred axis came out pointing back and the knee bent
    sideways, outwards (backwards once rolled). Roll the whole thigh/shin chain (controls, ORG, DEF, MCH) so X points sideways
    and Z back: a positive turn about X swings the foot back, a knee bending forward. Only rest frames
    change: the mesh doesn't move. Run before fix_controls, which picks the pole angle from these."""
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    n = 0
    for b in rig.data.edit_bones:
        if re.search(r"(thigh|shin)(?!_parent|_ik_target)", b.name) and re.search(r"\.[LR](\.\d+)?$", b.name):
            b.align_roll(Vector((0, 1, 0)))  # the character faces -Y: Z back
            n += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    # the legs rest slightly over-straight (knee behind the line), and the IK kept bending that way:
    # the knee went backwards. Only a forward bend (positive X) is allowed
    for s in ("L", "R"):
        pb = rig.pose.bones.get(f"MCH-shin_ik.{s}")
        if pb:
            pb.use_ik_limit_x, pb.ik_min_x, pb.ik_max_x = True, 0.0, math.radians(170)
            # a straight start leaves the solver stuck at the limit: it starts from this bend instead. Near
            # straight the bend barely changes the hip-ankle distance, so the standing pose keeps it: 1 degree
            # (feet ~3.5 mm off at rest) still swings the knee 10 cm forward when the foot rises 5 cm
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (math.radians(KNEE_START_BEND), 0.0, 0.0)
    return n


@contextlib.contextmanager
def others_aside(context, obj):
    """Gacha's NTE rigger works on the whole scene: it rebinds every mesh's Armature modifier to the
    new rig and, not finding the rig by name, post-processes the first armature in the scene (with
    two characters it rebuilt the first one's rig). Unlink everything that isn't this character
    while it runs, then put it back."""
    arm = obj.find_armature()
    pan = obj.get("st_panel")
    keep = {obj, arm, pan, *arm.children_recursive, *(pan.children_recursive if pan else ())}
    keep |= {v for v in obj.values() if isinstance(v, bpy.types.Object)}  # its sun and head empties
    sc = context.scene
    # whole collections where possible: Gacha deletes another character's WGTS_* collection if it
    # finds it empty
    def has_keep(c):
        return any(o in keep for o in c.all_objects)
    parked = [c for c in sc.collection.children if not has_keep(c)]
    # relinking resets each view layer's exclude / hide of a collection and the hide of an object:
    # remember them to put the user's hidden characters back hidden
    def layer_cols(lc):
        yield lc
        for ch in lc.children:
            yield from layer_cols(ch)
    flags = ("exclude", "hide_viewport", "holdout", "indirect_only")
    under = {x for p in parked for x in (p, *p.children_recursive)}
    col_state = [(vl, lc.collection, {f: getattr(lc, f) for f in flags}) for vl in sc.view_layers
                 for lc in layer_cols(vl.layer_collection) if lc.collection in under]
    for c in parked:
        sc.collection.children.unlink(c)
    moved = [(c, o) for c in (sc.collection, *sc.collection.children_recursive) for o in c.objects if o not in keep]
    obj_hidden = [(vl, o) for vl in sc.view_layers for _, o in moved if o.hide_get(view_layer=vl)]
    for c, o in moved:
        c.objects.unlink(o)
    # its face rig takes the first mesh with shape keys in bpy.data, scene or not: point it at this one
    from setup_wizard.character_rig_setup import nte_face_rig
    find_face = nte_face_rig.find_face_mesh
    nte_face_rig.find_face_mesh = lambda: obj
    # ...and deletes every WGT-Face_* object first, the other characters' face sliders included
    face_wgts = [(o, o.name) for o in bpy.data.objects if o.name.startswith("WGT-Face_")]
    for o, name in face_wgts:
        o.name = "ST " + name
    try:
        yield
    finally:
        nte_face_rig.find_face_mesh = find_face
        for o, name in face_wgts:
            o.name = name  # gets .001 if the new face made one with the same name
        for c in parked:
            try:
                sc.collection.children.link(c)
            except ReferenceError:  # removed by Gacha; its objects are relinked below if they were loose
                pass
        for c, o in moved:
            try:
                c.objects.link(o)
            except RuntimeError:  # already linked
                pass
            except ReferenceError:  # Gacha removed the collection
                if not o.users_collection:
                    sc.collection.objects.link(o)
        for vl, c, state in col_state:
            lc = next((x for x in layer_cols(vl.layer_collection) if x.collection == c), None)
            for f, v in (state.items() if lc else ()):
                setattr(lc, f, v)
        for vl, o in obj_hidden:
            if o.name in vl.objects:
                o.hide_set(True, view_layer=vl)


HEAD_TARGET, HEAD_TARGET_PARENTS = "head-controller", ("neck", "chest")  # the first the rig has
FINGER_MASTER = re.compile(r"(f_\w+|thumb)\.01_master\.[LR]")


POLE_DIST = 0.6  # m from the elbow / knee
POLES = "IK Poles"  # bone collection of the pole targets and their guide lines: hidden, toggled in the list
LIMBS = {  # limb: (Rigify bones upper / lower / end, pole parent (None: keep Gacha's), pole side: +Y back, -Y front)
    "arm": (("upper_arm", "forearm", "hand"), "Chest", 1),  # elbow target behind
    "leg": (("thigh", "shin", "foot"), None, -1),  # knee target in front (Gacha's parent: Hips)
}
# the panel's IK method (scene.strinova_ik_mode): with "ROTATION" every pole is set up but left off, so
# turning upper_arm_ik / thigh_ik swings the elbow / knee; Rigify's "Pole" switch turns one on, ready
IK_MODES = (("ROTATION", "Rotation", "Elbows and knees swing by rotating the arm and leg IK controls "
             "(upper_arm_ik, thigh_ik). Their poles are ready but off: Rigify's Pole switch turns them on"),
            ("POLES", "Poles", "Elbows and knees aim at pole targets, 60 cm away, shown in the IK Poles bone "
             "collection; the arm and leg IK controls' rotation does nothing then, so they are hidden"))
SHOULDER_TOGGLE = "Toggle Shoulder Constraints"
# Gacha's automatic-shoulder helpers, left in no bone collection (so always shown): one sits metres away
SHOULDER_HELPERS = ("MCH-shoulder_hand", "MCH-shoulder_follow", "shoulder_driver")
LIMB_SETTINGS = ("upper_arm_parent", "thigh_parent")  # hidden in "Other"
SHOULDER_OUT = 0.7  # shoulder control drawn this share of the way to the upper arm: its bone starts at the neck


def _enum_index(pb, prop, name):
    items = pb.id_properties_ui(prop).as_dict().get("items", [])
    return next((it[4] for it in items if it[1] == name), None)


def add_head_target_parent(rig, name):
    """Add `name` as one more parent of the head's look-at target (head-controller): Gacha's switch
    offers root, torso and chest, not the neck. Like the others: a target of the SWITCH PARENT
    Armature constraint, on when parent_switch equals its number (driver), and an item of the enum."""
    pb, mch = rig.pose.bones.get(HEAD_TARGET), rig.pose.bones.get(f"MCH-{HEAD_TARGET}-parent")
    con = mch.constraints.get("SWITCH PARENT") if mch else None
    if not (pb and con and name in rig.pose.bones and "parent_switch" in pb) or _enum_index(pb, "parent_switch", name) is not None:
        return
    t = con.targets.new()
    t.target, t.subtarget = rig, name
    i = len(con.targets)  # item 0 is "None": target k is item k + 1
    d = rig.driver_add(f'pose.bones["{mch.name}"].constraints["{con.name}"].targets[{i - 1}].weight').driver
    d.type, d.expression = "SCRIPTED", f"toggle == {i}"
    v = d.variables.new()
    v.name, v.targets[0].id = "toggle", rig
    v.targets[0].data_path = f'pose.bones["{HEAD_TARGET}"]["parent_switch"]'
    ui = pb.id_properties_ui("parent_switch")
    ui.update(items=[tuple(it) for it in ui.as_dict()["items"]] + [(f"P{i}", name, "", 0, i)])  # the whole list: update replaces it


def fix_limb_pole(context, rig, limb, side, pole_on):
    """Arms and legs with their pole on. Gacha leaves the pole IK muted, and the pole-less IK bends the
    limb the way its bones bend at rest: the arms rest in a T-pose while the character stands in an
    A-pose (moving the hand, the elbow flew up and out and the arm turned on itself), and the legs rest
    almost straight (knee 1.6 mm off the hip-ankle line on Eika), so lifting the foot sent the knee
    outwards. Here the pole IK takes over (as Rigify's own pole toggle does), its target sits right
    behind the elbow / in front of the knee, and its angle is the one that leaves the starting pose as
    it was. Without `pole_on` (the panel's Rotation method) the pole is then switched back off: turning
    upper_arm_ik / thigh_ik swings the elbow / knee."""
    (upper, lower, end), parent, way = LIMBS[limb]
    pb = rig.pose.bones
    joint, par, target = pb.get(f"MCH-{lower}_ik.{side}"), pb.get(f"{upper}_parent.{side}"), pb.get(f"{upper}_ik_target.{side}")
    cons = [c for c in joint.constraints if c.type == "IK"] if joint else []
    pole = next((c for c in cons if c.pole_target), None)
    if not (pole and par and target and "pole_vector" in par):
        return
    context.view_layer.update()
    names = (f"DEF-{upper}.{side}", f"DEF-{lower}.{side}", f"DEF-{end}.{side}")
    # the pose to keep: the arms' A-pose as evaluated (they rest in a T-pose); for the legs, standing is
    # their rest, and the pole-less IK's pose is the broken one (an FBX import came out twisted 90 degrees)
    keep = {n: (rig.data.bones[n].matrix_local if limb == "leg" else pb[n].matrix).copy() for n in names}
    root, joint_at, tip = pb[names[0]].head.copy(), pb[names[1]].head.copy(), pb[names[2]].head.copy()
    for c in cons:
        c.mute = c is not pole
    par["pole_vector"] = True
    i = _enum_index(par, "pole_parent", parent) if parent else None
    if i is not None:
        par["pole_parent"] = i
    rig.update_tag()
    context.view_layer.update()
    axis = (tip - root).normalized()
    out = Vector((0, way, 0))  # the character faces -Y
    out = (out - out.dot(axis) * axis).normalized()
    m = target.matrix.copy()
    m.translation = joint_at + out * POLE_DIST
    target.matrix = m
    # set and forget: out of the way in their own hidden collection, with Rigify's dashed guide line
    coll = rig.data.collections_all.get(POLES) or rig.data.collections.new(POLES)
    coll.is_visible = False
    for b in (target.bone, rig.data.bones.get(f"VIS_{upper}_ik_pole.{side}")):
        if b:
            for c in list(b.collections):
                c.unassign(b)
            coll.assign(b)

    # the foot follows its own control, not the pole: on an FBX its fixed offset from rest outweighed
    # every angle and they all tied
    measured = names if limb == "arm" else names[:2]

    def drift(angle):
        pole.pole_angle = angle
        context.view_layer.update()
        return max(pb[n].matrix.to_quaternion().rotation_difference(keep[n].to_quaternion()).angle for n in measured)

    # each try re-evaluates the scene (~40 ms): 15-degree sweep, then halve the step around the best (~37 tries, not 114)
    best, step = min((math.radians(a) for a in range(-180, 180, 15)), key=drift), math.radians(15)
    while step > math.radians(1):
        step /= 2
        best = min((best - step, best, best + step), key=drift)
    drift(best)
    if not pole_on:
        par["pole_vector"] = False  # Rigify's drivers swap the IK constraints back
        rig.update_tag()
        context.view_layer.update()


def fix_controls(context, rig, poles=False):
    """Gacha defaults that fight the animator (and the automatic shoulder, below):
    - the head's look-at target (head-controller) hangs from root.002, so turning the torso left
      the head staring at a fixed point and twisting. It now follows the neck (added to its parent
      switch, keeping where it is): turning the neck or the torso carries the head, and moving the
      target still aims it. Under the chest, bending the neck 80 degrees wrung the neck's mesh;
    - a finger master's location is copied to its finger's base, so scaling several to curl
      them (median pivot) also pulled them together and the hand looked smaller: their location
      is locked (they only rotate and scale)."""
    for pb in rig.pose.bones:
        if FINGER_MASTER.fullmatch(pb.name):
            pb.lock_location = (True, True, True)
    # Gacha's automatic shoulder aims at a shoulder_driver bone it places metres away (another game's
    # scale), almost opposite to the shoulder: any move of the hand spun the shoulder (over 100
    # degrees) and wrung the top of the arm. Off by default; the toggle stays on plate-settings.
    settings = rig.pose.bones.get("plate-settings")
    if settings and SHOULDER_TOGGLE in settings:
        settings[SHOULDER_TOGGLE] = 0
        rig.update_tag()
    other = rig.data.collections_all.get("Other") or rig.data.collections.new("Other")
    for side in ("L", "R"):
        for n in SHOULDER_HELPERS:
            b = rig.data.bones.get(f"{n}.{side}")
            if b and not b.collections:
                other.assign(b)
        # the limbs' settings holders (IK_FK, pole_vector...): they move nothing, and the panel shows
        # their settings with any control of the limb selected
        for n in LIMB_SETTINGS:
            b = rig.data.bones.get(f"{n}.{side}")
            if b:
                for c in list(b.collections):
                    c.unassign(b)
                other.assign(b)
        # only the drawing moves out, clear of the neck: the bone, the shoulder's pivot, stays
        pb, arm = rig.pose.bones.get(f"shoulder.{side}"), rig.data.bones.get(f"DEF-upper_arm.{side}")
        if pb and arm:
            out = arm.head_local - pb.bone.head_local
            out.y = 0.0  # sideways (and up), not back or forth
            pb.custom_shape_translation = pb.bone.matrix_local.to_3x3().inverted() @ (out * SHOULDER_OUT)
    if rig.name in context.view_layer.objects and rig.mode != "EDIT":
        for limb in LIMBS:
            for side in ("L", "R"):
                fix_limb_pole(context, rig, limb, side, poles)
        if poles:  # the poles steer elbows and knees: shown; turning the IK controls does nothing then: hidden
            if POLES in rig.data.collections_all:
                rig.data.collections_all[POLES].is_visible = True
            for (upper, _, _), _, _ in LIMBS.values():
                for side in ("L", "R"):
                    b = rig.data.bones.get(f"{upper}_ik.{side}")
                    if b:
                        for c in list(b.collections):
                            c.unassign(b)
                        other.assign(b)
    pb = rig.pose.bones.get(HEAD_TARGET)
    if not pb or "parent_switch" not in pb:
        return
    add_head_target_parent(rig, HEAD_TARGET_PARENTS[0])
    idx = next((i for i in (_enum_index(pb, "parent_switch", n) for n in HEAD_TARGET_PARENTS) if i is not None), None)
    if idx is None or pb["parent_switch"] == idx:
        return
    # only an evaluated pose can be read and written back: a rig in an excluded collection or in
    # edit mode has none (writing pb.matrix there crashed Blender), so it just switches parent
    live = rig.name in context.view_layer.objects and rig.mode != "EDIT"
    if live:
        context.view_layer.update()
        keep = pb.matrix.copy()
    pb["parent_switch"] = idx  # (not its UI default: updating it drops the switch's enum items)
    rig.update_tag()
    if live:
        context.view_layer.update()
        pb.matrix = keep
        context.view_layer.update()


class STRINOVA_OT_rig(bpy.types.Operator):
    bl_idname = "strinova.rig_physics"
    bl_label = "Generate rig"
    bl_description = "Generates the Rigify rig with Gacha Setup (NTE mode), with lighting controls and hair, clothes and chest physics"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_mesh(context) is not None

    def execute(self, context):
        prefs = context.preferences.addons
        if "setup_wizard" not in prefs:
            self.report({"ERROR"}, rpt_("Enable the Gacha Setup add-on"))
            return {"CANCELLED"}
        obj = target_mesh(context)
        arm = obj.find_armature()
        if not arm:
            self.report({"ERROR"}, rpt_("{} has no armature").format(obj.name))
            return {"CANCELLED"}
        if "Bip001-Pelvis" not in arm.data.bones:
            self.report({"ERROR"}, rpt_("{} is already rigged or is not a Strinova skeleton").format(arm.name))
            return {"CANCELLED"}
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = arm
        arm.select_set(True)
        bend_straight_fingers(context, arm)
        # the lighting panel is shading's business: it steps aside while Gacha's rigger runs and
        # joins the new rig afterwards
        with others_aside(context, obj), shading.lighting_panel_aside(context, obj):
            # NTE shares Strinova's hyphenated Bip001 skeleton, so Gacha Setup's NTE rigger maps it as is
            bpy.ops.hoyoverse.rig_character(game_type="NEVERNESS_TO_EVERNESS")
            rig = obj.find_armature()
            if not rig or "DEF-spine.006" not in rig.pose.bones:
                self.report({"ERROR"}, rpt_("Gacha Setup did not generate the rig (check the console)"))
                return {"CANCELLED"}
            # Strinova's weights are authored for rigid bones. Rigify's B-bones (8-10 segments) bend the
            # mesh differently and, since Gacha's NTE rigger flips the roll of consecutive spine bones,
            # tilting the chest twisted the torso. One segment deforms like the game.
            for b in rig.data.bones:
                if b.name.startswith("DEF-"):
                    b.bbone_segments = 1
            fix_thumb_axis(context, rig)
            fix_leg_axis(context, rig)  # knees bent sideways
            fix_finger_curl(rig)
            fix_breasts(context, rig)
            face.add_gaze(context, rig)
            eye_chains(context, rig)  # eye highlights filed as clothes (Eika S211)
            face.add_blink(context, rig, obj)  # before arrange_face, which lays its slider out
            face.arrange_face(context, rig, obj)
            face.add_face_bones(rig, obj)
            if not accessory.add_existing(rig, obj):  # masks with their own bone (Eika S111: mask_bone)
                accessory.add_headgear(context, rig, obj)  # else Eika's masks hang from hair_tt_*
            # head follows Gacha's head-controller (the target in front of the face) from the start;
            # the toggle stays on the gear bone (plate-settings) to turn it off
            settings = rig.pose.bones.get("plate-settings")
            if settings and "Use Head Controller" in settings:
                settings["Use Head Controller"] = 1
            fix_controls(context, rig, context.scene.strinova_ik_mode == "POLES")
        n = apply_inertia(rig)
        skirt.add(context, rig, obj)  # after the physics: the skirt bones are aimed at their children
        self.report({"INFO"}, rpt_("Rig ready: {}, {} chains with physics").format(rig.name, n))
        return {"FINISHED"}


classes = (STRINOVA_OT_rig,)
