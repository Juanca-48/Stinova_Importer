"""Weapons and props, imported on their own (never as part of a character).

A weapon skin is several models: the body, its sights and sometimes a pendant, each also in a lobby
version, and the body carries the sockets the game hangs the rest from:
    SK_Weap_M82_103                  body: bones Root, Magazine, Pull... and the sockets Sight, Pendant
    SK_Weap_M82_103_Sight_Mesh       sight (third person)        -> body's Sight bone
    SK_Weap_M82_103_Sight_1P_Mesh    sight for first person view: not brought (only by choosing it)
    SK_Weap_AA12_Pendant_113         pendant                     -> body's Pendant bone
    ... (lobby)                      the same pieces for the lobby (FBX tree) or in Mesh_Lobby (FModel)
Importing the body (or the skin's folder) brings its sight and pendant and hangs them in place;
importing any other piece brings just that piece.
"""
import bpy, os, re, math
from mathutils import Matrix, Vector, Quaternion
from bpy_extras.io_utils import ImportHelper
from . import importer, shading, common

PIECE_BONE = {"sight": "Sight", "pendant": "Pendant"}  # piece kind -> socket bone on the body


def weapon_name(path):
    """'Kanami_WT_206' from SK_Weap_Kanami_WT_206.uemodel."""
    return re.sub(r"^(SK_)?(Weap_)?", "", os.path.splitext(os.path.basename(path))[0], flags=re.I)


def piece_of(path):
    """(kind, view, lobby): kind body / sight / pendant; view '' / '1p' / 'jp'; lobby version or not."""
    s = os.path.splitext(os.path.basename(path))[0].lower()
    kind = "sight" if "sigh" in s else "pendant" if "pendant" in s else "body"  # 'Sigh_Mesh': a typo in the game
    view = next((v for v in ("1p", "jp") if re.search(rf"(^|_){v}(_|$)", s)), "")
    lobby = "lobby" in s or "lobby" in os.path.basename(os.path.dirname(path)).lower()
    return kind, view, lobby


def models_near(folder):
    """Models of a weapon skin: in its folder, and in Mesh / Mesh_Lobby subfolders (FModel's layout)."""
    out = []
    for d, _, files in os.walk(folder):
        if os.path.relpath(d, folder).count(os.sep) > 1:
            continue
        out += [os.path.join(d, f) for f in files if f.lower().endswith((".fbx", ".uemodel"))]
    return sorted(out)


def assembly(path, sight):
    """[body, pieces...] to import for a chosen body file or skin folder; [path] for any other piece.
    sight: bring the (third person) sight or not."""
    if os.path.isdir(path):
        folder = path
        files = models_near(path)
        bodies = sorted((f for f in files if piece_of(f)[0] == "body" and not piece_of(f)[1]), key=lambda f: piece_of(f)[2])
        if not bodies:
            return files[:1]
        body = bodies[0]  # the normal version over the lobby one
    else:
        body = path
        kind, view, _ = piece_of(body)
        if kind != "body" or view:
            return [body]
        folder = os.path.dirname(body)
        if os.path.basename(folder).lower().startswith("mesh"):  # FModel: Mesh and Mesh_Lobby side by side
            folder = os.path.dirname(folder)
        files = models_near(folder)
    lobby = piece_of(body)[2]
    same = [f for f in files if piece_of(f)[2] == lobby and f != body]
    pieces = []
    if sight:
        def sight_in(fs):  # the normal sight: not the first person (_1P) one nor the _JP piece
            return [f for f in fs if piece_of(f)[0] == "sight" and piece_of(f)[2] == lobby and not piece_of(f)[1]]

        # a skin without its own sight uses the base weapon's (Base in the FBX tree, S000 in FModel's)
        base = next((os.path.join(os.path.dirname(folder), b) for b in ("Base", "S000")
                     if os.path.isdir(os.path.join(os.path.dirname(folder), b))), None)
        pieces += (sight_in(same) or (sight_in(models_near(base)) if base and base != folder else []))[:1]
    pieces += [f for f in same if piece_of(f)[0] == "pendant"]
    return [body] + pieces


def assets_root(path, char_dir):
    """FModel's SkinAssets folder (weapon textures and materials in Weapons, the metal matcap in
    Characters/PBR): from the model's own path, or from the panel's character folder for an FBX."""
    for p in (path, char_dir):
        parts = os.path.normpath(bpy.path.abspath(p)).split(os.sep) if p else []
        if "SkinAssets" in parts:
            return os.sep.join(parts[: parts.index("SkinAssets") + 1])
    return None


def import_file(path):
    """New objects of one imported model."""
    before = set(bpy.data.objects)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=True)
    else:
        d, f = os.path.split(path)
        bpy.ops.uf.import_uemodel(filepath=path, directory=d, files=[{"name": f}])
    return [o for o in bpy.data.objects if o not in before]


def hang(context, objs, body_arm, bone_name):
    """Put a piece where the game draws it: its root bone on the body's socket bone, then parented to
    that bone so it follows the weapon."""
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    top = arm or next(o for o in objs if o.parent is None)
    bone = body_arm.data.bones.get(bone_name)
    if not bone:
        return False
    root = arm.data.bones[0].matrix_local if arm and arm.data.bones else Matrix.Identity(4)  # static mesh: its origin
    context.view_layer.update()
    top.matrix_world = body_arm.matrix_world @ bone.matrix_local @ root.inverted()
    shading._reparent(context, top, body_arm, bone_name)
    return True


PIECE_LABEL = {"sight": "Mira", "pendant": "Colgante"}  # bone names of a piece once joined to the weapon's rig


def join_piece(context, body_arm, objs, socket, label):
    """Merge a hung piece's own skeleton (a sight's scope parts, a pendant's chain) into the weapon's,
    its root under the socket bone, so the whole weapon is one rig. Its bones are renamed by role
    (Mira, Mira Root_01...; Blender renames the vertex groups too). Returns the piece's root bone,
    or None for a piece without skeleton (it stays parented to the socket)."""
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    if not arm or not arm.data.bones:
        return None
    root = next(b for b in arm.data.bones if not b.parent)
    for b in list(arm.data.bones):
        if b != root:
            b.name = f"{label} {b.name}"
    root.name = label
    label = root.name  # Blender may add .001 if the rig already has one
    kids = [o for o in objs if o.type == "MESH"]
    context.view_layer.update()  # hang() just moved their parent: read where they are now
    kept = {m: m.matrix_world.copy() for m in kids}  # the join reparents them without keeping where they are
    for o in context.view_layer.objects:
        o.select_set(False)
    body_arm.select_set(True)
    arm.select_set(True)
    context.view_layer.objects.active = body_arm
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode="EDIT")
    eb = body_arm.data.edit_bones
    eb[label].parent = eb.get(socket)
    eb[label].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for m in kids:  # the join leaves them pointing at the merged-away skeleton, and moved
        for mod in m.modifiers:
            if mod.type == "ARMATURE":
                mod.object = body_arm
        m.parent, m.parent_type = body_arm, "OBJECT"
        m.matrix_parent_inverse = body_arm.matrix_world.inverted()
        m.matrix_world = kept[m]
    return label


# ---------- controls ----------
CONTROLS = "Arma"  # bone collection with the controls
SOCKETS = "Sockets"  # game attachment points (muzzle, shell drop, camera...): hidden
ROOT_COLOR = (1.0, 0.75, 0.1)
PART_COLOR = (0.2, 0.75, 1.0)
PIECE_COLOR = (1.0, 0.35, 0.6)  # sight and pendant holders
SUPPORT_COLOR = (0.35, 1.0, 0.4)  # where the left hand goes
PAD = 0.01


def _shape(name, verts, edges):
    return shading._mesh_obj(name, verts, None, None, None, edges=edges)


def _side_widget(pb, rig_points, kind):
    """Custom shape in the weapon's side view (the YZ plane of the rig: barrel along Y, up Z), turned
    out of the bone's own axes, around `rig_points` (rig space)."""
    lo = [min(p[i] for p in rig_points) for i in range(3)]
    hi = [max(p[i] for p in rig_points) for i in range(3)]
    center = Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
    if kind == "root":  # rectangle around the whole weapon
        shape = _shape("WGT-ST_weapon_root", [(0, -0.5, -0.5), (0, 0.5, -0.5), (0, 0.5, 0.5), (0, -0.5, 0.5)],
                       [(0, 1), (1, 2), (2, 3), (3, 0)])
        scale = (1.0, hi[1] - lo[1] + 2 * PAD, hi[2] - lo[2] + 2 * PAD)
    else:  # circle around the part
        n = 24
        shape = _shape("WGT-ST_weapon_part", [(0, math.cos(math.tau * i / n), math.sin(math.tau * i / n)) for i in range(n)],
                       [(i, (i + 1) % n) for i in range(n)])
        r = min(0.05, max(0.012, 0.5 * max(hi[1] - lo[1], hi[2] - lo[2]) + PAD / 2))  # long parts (bolt, blade): capped
        scale = (r, r, r)
    bone = pb.bone
    rot = bone.matrix_local.to_3x3().normalized().inverted()
    pb.custom_shape = shape
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_rotation_euler = rot.to_euler()
    pb.custom_shape_translation = rot @ (center - bone.head_local)
    pb.custom_shape_scale_xyz = scale


def rig_weapon(context, arm, meshes, pieces):
    """Controls for a weapon's skeleton: Root as a frame around the weapon, a circle on every bone that
    moves part of the mesh (magazine, bolt, suppressor, foregrip, a katana's blade...) and on the bones
    holding the sight and pendant. The game's sockets go to a hidden collection.
    pieces: {bone name: [objects hung from it]}."""
    to_rig = arm.matrix_world.inverted()
    pts = {}  # bone -> rig-space points it moves
    for m in meshes:
        mw = m.matrix_world
        groups = {g.index: g.name for g in m.vertex_groups} if m.find_armature() == arm else {}
        for v in m.data.vertices:
            p = to_rig @ (mw @ v.co)
            pts.setdefault("*", []).append(p)
            for g in v.groups:
                if g.weight > 0.5 and g.group in groups:
                    pts.setdefault(groups[g.group], []).append(p)
    for bone, objs in pieces.items():
        for o in objs:
            if o.type == "MESH":
                pts.setdefault(bone, []).extend(to_rig @ (o.matrix_world @ Vector(c)) for c in o.bound_box)
    root = next((b.name for b in arm.data.bones if not b.parent), None)
    coll_c = arm.data.collections.get(CONTROLS) or arm.data.collections.new(CONTROLS)
    coll_s = arm.data.collections.get(SOCKETS) or arm.data.collections.new(SOCKETS)
    controls = 0
    for b in arm.data.bones:
        pb = arm.pose.bones[b.name]
        for c in list(b.collections):
            c.unassign(b)
        if b.name == root and pts.get("*"):
            _side_widget(pb, pts["*"], "root")
            common.paint(arm, b.name, ROOT_COLOR)
        elif b.name in pts and b.name != root:
            _side_widget(pb, pts[b.name], "part")
            piece = b.name in pieces or b.name.startswith(tuple(f"{l} " for l in PIECE_LABEL.values()))
            common.paint(arm, b.name, PIECE_COLOR if piece else PART_COLOR)
        else:
            coll_s.assign(b)
            continue
        coll_c.assign(b)
        controls += 1
    coll_s.is_visible = False
    arm.show_in_front = True
    arm["st_weapon_rig"] = True  # found from any selected part when connecting to a hand
    return controls


# ---------- hands ----------
GRIP_PROP, SUPPORT_PROP = "st_grip", "st_support"  # weapon rig toggles: right hand (trigger), left hand (support)
GRIP_CON, SUPPORT_CON = "ST Mano derecha", "ST Mano izquierda"
SUPPORT = "Soporte"  # weapon bone the left hand goes to
RIGHT_HAND, LEFT_HAND, LEFT_IK, LEFT_ARM = "DEF-hand.R", "DEF-hand.L", "hand_ik.L", "upper_arm_parent.L"
RIGHT_IK, RIGHT_ARM, CHEST = "hand_ik.R", "upper_arm_parent.R", "DEF-spine.003"
# starting pose: the game's idle "low ready" (Referencias, shooting gallery): grip at the right side of
# the waist, stock along the right ribs, barrel forward and down across the body toward the left
HOLD = Vector((-0.12, -0.14, -0.24))  # grip, from the chest (rig space): to the right, forward, down to the waist
HOLD_PITCH, HOLD_YAW = 20.0, 25.0  # degrees: barrel down, and turned toward the character's left
GRIP_IN = 0.07  # grip: this far from the wrist along the fingers...
GRIP_DOWN = 0.025  # ...and this far below, at rest (palm down in the T-pose)


def weapon_rig(ob):
    """The weapon armature of a selected weapon object (its rig, a mesh or a hung piece)."""
    while ob and not ob.get("st_weapon_rig"):
        ob = ob.parent
    return ob


def grip_frame(rig, hand_bone=None):
    """Where a weapon point held in a hand sits, in the character rig's space, with the hand at rest:
    in the palm, barrel along the fingers, the weapon's top toward the thumb (forward). Arm forward, the
    weapon aims forward and upright. The game's own hand socket (ik_hand_gun) carries a rotation the
    export lacks, so this is set here; the weapon's Root control fine-tunes it."""
    hand = rig.data.bones[hand_bone or RIGHT_HAND]
    d = (hand.tail_local - hand.head_local).normalized()
    t = Vector((0, -1, 0))
    t = (t - t.dot(d) * d).normalized()
    y, z = -d, t
    rot = Matrix((y.cross(z), y, z)).transposed().to_4x4()
    return Matrix.Translation(hand.head_local + d * GRIP_IN + Vector((0, 0, -GRIP_DOWN))) @ rot


def support_point(arm):
    """The left hand's place on the weapon (weapon armature space): its foregrip if it has one, else
    under the barrel 30% of the way from the grip to the muzzle."""
    if "Foregrip" in arm.data.bones:
        return arm.data.bones["Foregrip"].head_local.copy()
    root = arm.data.bones["Root"].head_local
    pts = [arm.matrix_world.inverted() @ (m.matrix_world @ v.co) for m in arm.children if m.type == "MESH"
           and m.find_armature() == arm and not m.name.startswith("WGT") for v in m.data.vertices]
    if not pts:
        return root + Vector((0, -0.25, -0.03))
    y = root.y + (min(p.y for p in pts) - root.y) * 0.3
    near = [p.z for p in pts if abs(p.y - y) < 0.02] or [root.z]
    return Vector((root.x, y, min(near)))


def hold_pose(context, arm, rig):
    """A starting pose when the right arm is untouched: its IK hand moved so the weapon is held like the
    game's idle (low ready), the left hand then reaching its support. An arm already posed is left
    alone."""
    ik = rig.pose.bones.get(RIGHT_IK)
    if not ik or CHEST not in rig.data.bones or ik.location.length > 1e-4 or ik.rotation_quaternion != Quaternion()             or any(abs(a) > 1e-4 for a in ik.rotation_euler):
        return False
    if RIGHT_ARM in rig.pose.bones and "IK_FK" in rig.pose.bones[RIGHT_ARM]:
        rig.pose.bones[RIGHT_ARM]["IK_FK"] = 0.0
    grip = rig.data.bones[CHEST].head_local + HOLD
    root = arm.data.bones["Root"]
    # weapon object upright, barrel down and to the left (its Root on the grip point); the hand where
    # that weapon needs it
    tilt = Matrix.Rotation(math.radians(HOLD_YAW), 4, "Z") @ Matrix.Rotation(math.radians(HOLD_PITCH), 4, "X")
    weapon = Matrix.Translation(grip) @ tilt @ Matrix.Translation(-root.head_local)
    hand = rig.data.bones[RIGHT_HAND]
    rel = hand.matrix_local.inverted() @ grip_frame(rig) @ Matrix.Translation(-root.head_local)
    ik.matrix = weapon @ rel.inverted() @ hand.matrix_local.inverted() @ rig.data.bones[RIGHT_IK].matrix_local
    context.view_layer.update()
    return True


def drive_influence(con, owner, prop):
    con.driver_remove("influence")
    d = con.driver_add("influence").driver
    d.type = "SCRIPTED"
    v = d.variables.new()
    v.name, v.type = "v", "SINGLE_PROP"
    v.targets[0].id, v.targets[0].data_path = owner, f'["{prop}"]'
    d.expression = "v"


def disconnect(arm):
    """Remove the weapon's hand constraints, on itself and on the rig it was connected to."""
    c = arm.constraints.get(GRIP_CON)
    if c:
        arm.constraints.remove(c)
    rig = arm.get("st_hand_rig")
    pb = rig.pose.bones.get(LEFT_IK) if isinstance(rig, bpy.types.Object) else None
    if pb and pb.constraints.get(SUPPORT_CON):
        pb.constraints.remove(pb.constraints[SUPPORT_CON])


def connect(context, arm, rig):
    """Weapon in the right hand of `rig` (it follows the hand) and the left hand on its Soporte bone
    (by IK). Each one has its own animatable toggle on the weapon rig."""
    disconnect(arm)
    for prop, desc in ((GRIP_PROP, "El arma sigue la mano derecha del personaje (gatillo)"),
                       (SUPPORT_PROP, "La mano izquierda del personaje va al soporte del arma")):
        if prop not in arm:
            arm[prop] = True
            arm.id_properties_ui(prop).update(description=desc)
    arm.update_tag()
    root = arm.data.bones["Root"]
    hand = rig.data.bones[RIGHT_HAND]
    # right hand: world = hand now @ (hand at rest -> grip) @ weapon object from its Root; the
    # weapon's own transform stays as it was, so the toggle off puts it back there
    grip = hand.matrix_local.inverted() @ grip_frame(rig) @ Matrix.Translation(-root.head_local)
    c = arm.constraints.new("CHILD_OF")
    c.name, c.target, c.subtarget = GRIP_CON, rig, RIGHT_HAND
    c.inverse_matrix = grip @ arm.matrix_basis.inverted()
    drive_influence(c, arm, GRIP_PROP)
    context.view_layer.update()
    hold_pose(context, arm, rig)
    # left hand: a Soporte bone on the weapon where the left wrist goes for its palm to be on the support
    # point, turned by the same rule as the right hand (fingers along the barrel, thumb up)
    hand_l = rig.data.bones[LEFT_HAND]
    want = arm.matrix_world @ Matrix.Translation(support_point(arm)) @ grip_frame(rig, LEFT_HAND).inverted() @ hand_l.matrix_local
    for o in context.view_layer.objects:
        o.select_set(False)
    context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    s = eb.get(SUPPORT) or eb.new(SUPPORT)
    s.parent, s.use_deform = eb["Root"], False
    s.head, s.tail = Vector((0, 0, 0)), Vector((0, 0.05, 0))
    s.matrix = arm.matrix_world.inverted() @ want
    bpy.ops.object.mode_set(mode="OBJECT")
    pb = arm.pose.bones[SUPPORT]
    pb.location, pb.rotation_quaternion, pb.rotation_euler = (0, 0, 0), (1, 0, 0, 0), (0, 0, 0)
    coll = arm.data.collections.get(CONTROLS) or arm.data.collections.new(CONTROLS)
    for col in list(pb.bone.collections):
        col.unassign(pb.bone)
    coll.assign(pb.bone)
    _side_widget(pb, [pb.bone.head_local], "part")
    pb.custom_shape_translation = (0, GRIP_IN, 0)  # the bone is the wrist: draw it at the palm, on the weapon
    common.paint(arm, SUPPORT, SUPPORT_COLOR)
    if LEFT_ARM in rig.pose.bones and "IK_FK" in rig.pose.bones[LEFT_ARM]:
        rig.pose.bones[LEFT_ARM]["IK_FK"] = 0.0  # the left arm in IK, so its hand control leads
    ct = rig.pose.bones[LEFT_IK].constraints.new("COPY_TRANSFORMS")
    ct.name, ct.target, ct.subtarget = SUPPORT_CON, arm, SUPPORT
    drive_influence(ct, arm, SUPPORT_PROP)
    arm["st_hand_rig"] = rig
    # light it like the character, so it matches the hand
    host = next((m for m in bpy.data.objects if m.type == "MESH" and m.find_armature() == rig
                 and m.get("st_light") and not m.get("st_paper")), None)
    meshes = [m for m in bpy.data.objects if m.type == "MESH" and m.get("st_weapon") and weapon_rig(m) == arm]
    if host and meshes:
        shading.light_weapon(meshes, host)
    return host


class STRINOVA_OT_weapon_hand(bpy.types.Operator):
    bl_idname = "strinova.weapon_hand"
    bl_label = "Conectar a la mano"
    bl_description = ("Con el arma y un personaje seleccionados: el arma va a su mano derecha (gatillo) y su mano "
                      "izquierda al soporte del arma. Cada mano tiene su interruptor en el panel")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sel = list(context.selected_objects) + [context.active_object]
        arm = next((weapon_rig(o) for o in sel if weapon_rig(o)), None)
        rig = next((o.find_armature() if o.type == "MESH" else o for o in sel if o and not weapon_rig(o)
                    and (o.find_armature() if o.type == "MESH" else o) is not None
                    and RIGHT_HAND in getattr((o.find_armature() if o.type == "MESH" else o).data, "bones", {})), None)
        if not arm or not rig:
            self.report({"ERROR"}, "Selecciona el arma y el personaje (su rig o su malla) a la vez")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        host = connect(context, arm, rig)
        self.report({"INFO"}, f"{arm.name} en la mano de {rig.name}" + (f", con la luz de {host.name}" if host else ""))
        return {"FINISHED"}


class STRINOVA_OT_import_weapon(bpy.types.Operator, ImportHelper):
    bl_idname = "strinova.import_weapon"
    bl_label = "Importar arma"
    bl_description = ("Importa un arma (.uemodel o .fbx) en su propia coleccion. Con el cuerpo del arma o la carpeta "
                      "de la skin, trae tambien su mira y su colgante y los coloca en su sitio")
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(default="*.uemodel;*.fbx", options={"HIDDEN"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    sight: bpy.props.BoolProperty(name="Incluir mira", default=True,
                                  description="Trae la mira del arma y la coloca en su sitio; sin ella, solo el cuerpo")

    def execute(self, context):
        path = self.filepath
        if not os.path.isfile(path):  # no file picked: the skin folder the browser shows
            path = next((d for d in (path, self.directory, os.path.dirname(path)) if d and os.path.isdir(d)), "")
        files = assembly(path, self.sight) if path else []
        if not files:
            self.report({"ERROR"}, "Elige el arma (.uemodel o .fbx) o la carpeta de una de sus skins")
            return {"CANCELLED"}
        if any(f.lower().endswith(".uemodel") for f in files) and not hasattr(bpy.types, "UF_OT_import_uemodel"):
            self.report({"ERROR"}, "UEFormat no esta activo: activalo o importa el arma como .fbx")
            return {"CANCELLED"}
        # light the weapon like the selected character (its sun and colours), else with its own sun
        host = common.target_mesh(context)
        if host and host.get("st_weapon"):  # a weapon selected: the character that lights it
            host = host.get("st_weapon_host")
        host = host if host and host.get("st_light") and not host.get("st_paper") else None
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        # own collection, active while importing, like a character (see importer.execute)
        vl = context.view_layer
        prev_active = vl.active_layer_collection
        coll = bpy.data.collections.new(f"Arma {weapon_name(files[0])}")
        context.scene.collection.children.link(coll)
        vl.active_layer_collection = importer._layer_collection(vl.layer_collection, coll)
        before, before_colls = set(bpy.data.objects), set(bpy.data.collections)
        hung, pieces, controls = [], {}, 0
        try:
            body = import_file(files[0])
            body_arm = next((o for o in body if o.type == "ARMATURE"), None)
            for f in files[1:]:
                objs = import_file(f)
                kind = piece_of(f)[0]
                if body_arm and objs and hang(context, objs, body_arm, PIECE_BONE[kind]):
                    hung.append(kind)
                    meshes_k = [o for o in objs if o.type == "MESH"]
                    label = join_piece(context, body_arm, objs, PIECE_BONE[kind], PIECE_LABEL[kind])
                    pieces.setdefault(label or PIECE_BONE[kind], []).extend(meshes_k)
            if body_arm:
                controls = rig_weapon(context, body_arm, [o for o in body if o.type == "MESH"] + sum(pieces.values(), []), pieces)
        finally:
            importer.gather_leftovers(context, coll, before, before_colls)
            vl.active_layer_collection = prev_active
        new = [o for o in bpy.data.objects if o not in before and not o.name.startswith("WGT-")]  # not the control shapes
        if not new:
            bpy.data.collections.remove(coll)
            self.report({"ERROR"}, "El archivo no trae ningun modelo")
            return {"CANCELLED"}
        for o in vl.objects:
            o.select_set(False)
        meshes = [o for o in new if o.type == "MESH"]
        shaded = ""
        if meshes and context.scene.strinova_do_shading:
            root = assets_root(files[0], context.scene.strinova_char_dir)
            if root:
                report = shading.shade_weapon(context, meshes, root, host)
                for k, v in report.items():
                    print(f"[Strinova] {k}: {v}")
                done = sum(isinstance(v, dict) for v in report.values())
                shaded = f", {done}/{len(report)} materiales" + (f" con la luz de {host.name}" if host else "")
            else:
                shaded = ", sin shading: no encuentro la carpeta SkinAssets de FModel (revisa la carpeta del personaje)"
        for o in meshes:
            o.select_set(True)
        vl.objects.active = meshes[0] if meshes else new[0]
        extra = f", con {' y '.join({'sight': 'mira', 'pendant': 'colgante'}[k] for k in hung)}" if hung else ""
        self.report({"INFO"}, f"{coll.name}: {len(meshes)} malla(s){extra}, {controls} controles{shaded}")
        return {"FINISHED"}


classes = (STRINOVA_OT_import_weapon, STRINOVA_OT_weapon_hand)
