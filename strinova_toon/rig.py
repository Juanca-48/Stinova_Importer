"""Rig: Rigify rig through Gacha Setup's NTE rigger, Strinova-specific fixes on top of it, and the
constraint 'physics' for hair, clothes and chest."""
import bpy, re, contextlib
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
    flipped = []
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
            if backwards:
                flipped.append(f + side)
    return flipped


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
    for c in parked:
        sc.collection.children.unlink(c)
    moved = [(c, o) for c in (sc.collection, *sc.collection.children_recursive) for o in c.objects if o not in keep]
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
            face.arrange_face(context, rig, obj)
            face.add_face_bones(rig, obj)
            if not accessory.add_existing(rig, obj):  # masks with their own bone (Eika S111: mask_bone)
                accessory.add_headgear(context, rig, obj)  # else Eika's masks hang from hair_tt_*
            # head follows Gacha's head-controller (the target in front of the face) from the start;
            # the toggle stays on the gear bone (plate-settings) to turn it off
            settings = rig.pose.bones.get("plate-settings")
            if settings and "Use Head Controller" in settings:
                settings["Use Head Controller"] = 1
        n = apply_inertia(rig)
        self.report({"INFO"}, f"Rig listo: {rig.name}, {n} cadenas con fisica")
        return {"FINISHED"}


classes = (STRINOVA_OT_rig,)
