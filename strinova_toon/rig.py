"""Rig: Rigify rig through Gacha Setup's NTE rigger, Strinova-specific fixes on top of it, and the
constraint 'physics' for hair, clothes and chest."""
import bpy, re, math, contextlib
from mathutils import Vector
from .common import target_mesh
from . import shading, face, accessory

# ---------- rig + physics ----------
PHYS_COLLECTIONS = ("Hair", "Clothes")
NOT_PHYSICS = {"SocketADS"}  # gameplay socket Gacha Setup files under Clothes


PHYSICS_PROP = "st_physics"  # on/off toggle: multiplies every inertia influence, live and animatable
INERTIA_PROPS = {  # group: (rig property, default influence, panel label)
    # 20% stiffer than Gacha Setup's 0.7 / 0.4: theirs felt too loose on Strinova's chains
    "Hair": ("st_hair_inertia", 0.56, "Inercia pelo"),
    "Bangs": ("st_bangs_inertia", 0.28, "Inercia flequillo"),  # bangs sway half as much as the back hair
    "Clothes": ("st_cloth_inertia", 0.32, "Inercia ropa"),
    "Breast": ("st_breast_inertia", 0.2, "Inercia pecho"),
}


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
        rig.id_properties_ui(prop).update(min=0.0, max=1.0, description=f"{label}: cuanto se retrasa y arrastra al animar")
    if PHYSICS_PROP not in rig:
        rig[PHYSICS_PROP] = True
    rig.id_properties_ui(PHYSICS_PROP).update(description="Activa la fisica de pelo, ropa y pecho")

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


HEAD_TARGET, HEAD_TARGET_PARENT = "head-controller", "chest"
FINGER_MASTER = re.compile(r"(f_\w+|thumb)\.01_master\.[LR]")


POLE_PARENT, POLE_DIST = "Chest", 0.4


def _enum_index(pb, prop, name):
    items = pb.id_properties_ui(prop).as_dict().get("items", [])
    return next((it[4] for it in items if it[1] == name), None)


def fix_arm_pole(context, rig, side):
    """Arms with their elbow pole on. Gacha leaves the pole IK muted, and the pole-less IK twists the
    arm from the bones' rest (a T-pose) while the character stands in an A-pose: moving the hand,
    the elbow flew up and out and the arm turned on itself. Here the pole IK takes over (as Rigify's
    own pole toggle does), its target hangs from the chest right behind the elbow, and its angle is
    the one that leaves the starting pose as it was."""
    pb = rig.pose.bones
    joint, par, target = pb.get(f"MCH-forearm_ik.{side}"), pb.get(f"upper_arm_parent.{side}"), pb.get(f"upper_arm_ik_target.{side}")
    cons = [c for c in joint.constraints if c.type == "IK"] if joint else []
    pole = next((c for c in cons if c.pole_target), None)
    if not (pole and par and target and "pole_vector" in par):
        return
    context.view_layer.update()
    names = (f"DEF-upper_arm.{side}", f"DEF-forearm.{side}", f"DEF-hand.{side}")
    keep = {n: pb[n].matrix.copy() for n in names}
    shoulder, elbow, wrist = pb[names[0]].head.copy(), pb[names[1]].head.copy(), pb[names[2]].head.copy()
    for c in cons:
        c.mute = c is not pole
    par["pole_vector"] = True
    chest = _enum_index(par, "pole_parent", POLE_PARENT)
    if chest is not None:
        par["pole_parent"] = chest
    rig.update_tag()
    context.view_layer.update()
    axis = (wrist - shoulder).normalized()
    back = Vector((0, 1, 0))  # the character faces -Y
    back = (back - back.dot(axis) * axis).normalized()
    m = target.matrix.copy()
    m.translation = elbow + back * POLE_DIST
    target.matrix = m

    def drift(angle):
        pole.pole_angle = angle
        context.view_layer.update()
        return max(pb[n].matrix.to_quaternion().rotation_difference(keep[n].to_quaternion()).angle for n in names)

    best = min((math.radians(a) for a in range(-180, 180, 5)), key=drift)
    best = min((best + math.radians(a) / 4 for a in range(-20, 21)), key=drift)
    drift(best)


def fix_controls(context, rig):
    """Two Gacha defaults that fight the animator:
    - the head's look-at target (head-controller) hangs from root.002, so turning the torso left
      the head staring at a fixed point and twisting: it now follows the chest (its own parent
      switch, keeping where it is);
    - a finger master's location is copied to its finger's base, so scaling several to curl
      them (median pivot) also pulled them together and the hand looked smaller: their location
      is locked (they only rotate and scale)."""
    for pb in rig.pose.bones:
        if FINGER_MASTER.fullmatch(pb.name):
            pb.lock_location = (True, True, True)
    if rig.name in context.view_layer.objects and rig.mode != "EDIT":
        for side in ("L", "R"):
            fix_arm_pole(context, rig, side)
    pb = rig.pose.bones.get(HEAD_TARGET)
    if not pb or "parent_switch" not in pb:
        return
    items = pb.id_properties_ui("parent_switch").as_dict().get("items", [])
    idx = next((it[4] for it in items if it[1] == HEAD_TARGET_PARENT), None)
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
    bl_label = "Generar rig"
    bl_description = "Genera el rig Rigify con Gacha Setup (modo NTE), con controles de luz y fisica de pelo, ropa y pecho"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_mesh(context) is not None

    def execute(self, context):
        prefs = context.preferences.addons
        if "setup_wizard" not in prefs:
            self.report({"ERROR"}, "Activa el add-on Gacha Setup")
            return {"CANCELLED"}
        obj = target_mesh(context)
        arm = obj.find_armature()
        if not arm:
            self.report({"ERROR"}, f"{obj.name} no tiene armature")
            return {"CANCELLED"}
        if "Bip001-Pelvis" not in arm.data.bones:
            self.report({"ERROR"}, f"{arm.name} ya esta riggeado o no es un esqueleto de Strinova")
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
                self.report({"ERROR"}, "Gacha Setup no genero el rig (revisa la consola)")
                return {"CANCELLED"}
            # Strinova's weights are authored for rigid bones. Rigify's B-bones (8-10 segments) bend the
            # mesh differently and, since Gacha's NTE rigger flips the roll of consecutive spine bones,
            # tilting the chest twisted the torso. One segment deforms like the game.
            for b in rig.data.bones:
                if b.name.startswith("DEF-"):
                    b.bbone_segments = 1
            fix_finger_curl(rig)
            fix_breasts(context, rig)
            face.add_gaze(context, rig)
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
            fix_controls(context, rig)
        n = apply_inertia(rig)
        self.report({"INFO"}, f"Rig listo: {rig.name}, {n} cadenas con fisica")
        return {"FINISHED"}


classes = (STRINOVA_OT_rig,)
