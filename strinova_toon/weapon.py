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
from bpy_extras import view3d_utils
from . import importer, shading, common
from .common import iface_, tip_, rpt_

PIECE_BONE = {"sight": "Sight", "pendant": "Pendant", "magazine": "Magazine"}  # piece kind -> socket bone on the body


def weapon_name(path):
    """'Kanami_WT_206' from SK_Weap_Kanami_WT_206.uemodel."""
    return re.sub(r"^(SK_)?(Weap_)?", "", os.path.splitext(os.path.basename(path))[0], flags=re.I)


def piece_of(path):
    """(kind, view, lobby): kind body / sight / pendant / magazine; view '' / '1p' / 'jp'; lobby version or not."""
    s = os.path.splitext(os.path.basename(path))[0].lower()
    # the game's own typos: Sigh_Mesh, Pandant, Pendent, Magzine
    kind = ("sight" if "sigh" in s else "pendant" if re.search(r"p[ae]nd[ae]nt", s)
            else "magazine" if re.search(r"maga?zine", s) else "body")
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
    # a separate magazine (P90, some AKM skins) only from its own folder: other bodies carry theirs
    pieces += [f for f in same if piece_of(f)[0] == "magazine" and not piece_of(f)[1]][:1]
    return [body] + pieces


def assets_root(path, char_dir, meshes=()):
    """Where a weapon's textures (and material JSONs) are: FModel's SkinAssets folder if the model is in
    it (weapon textures in Weapons, the metal matcap in Characters/PBR); else, like a character, the
    nearest folder around the model holding the textures its materials name in the bundled table (a
    weapon missing from it: its material JSONs); else SkinAssets from the panel's Root folder or
    from the FModel export remembered in the preferences."""
    def in_skin_assets(p):
        return p and "SkinAssets" in os.path.normpath(bpy.path.abspath(p)).split(os.sep)

    if in_skin_assets(path):
        return common.skin_assets(path)
    names = set().union(*(shading.texture_names(m, weapon=True) for m in meshes))
    mats = {re.sub(r"\.\d{3}$", "", s.material.name).lower() for m in meshes for s in m.material_slots
            if s.material and not s.material.name.endswith(shading.OUTLINE_SUFFIX)}
    # never "any PNG": climbing from a weapon folder would stop at the characters' textures
    found = shading.texture_root(path, names) if names else shading.texture_root(path, mats, ".json") if mats else None
    if found:
        return found
    return common.skin_assets(char_dir) if in_skin_assets(char_dir) else common.fmodel_root()


def import_file(path):
    """New objects of one imported model."""
    before = set(bpy.data.objects)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=False)  # as the character's: keep the real tip bones
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


def carries(objs, bone):
    """A body mesh already skinned to this socket bone (it has the piece built in)."""
    for m in objs:
        g = m.vertex_groups.get(bone) if m.type == "MESH" else None
        if g and any(e.group == g.index and e.weight > 0.5 for v in m.data.vertices for e in v.groups):
            return True
    return False


PIECE_LABEL = {"sight": "Sight Part", "pendant": "Pendant Part", "magazine": "Magazine Part"}  # bone names of a piece once joined to the weapon's rig


def join_piece(context, body_arm, objs, socket, label):
    """Merge a hung piece's own skeleton (a sight's scope parts, a pendant's chain) into the weapon's,
    its root under the socket bone, so the whole weapon is one rig. Its bones are renamed by role
    (Sight Part, Sight Part Root_01...; Blender renames the vertex groups too). Returns the piece's root bone,
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
CONTROLS = "Weapon"  # bone collection with the controls
SOCKETS = "Sockets"  # game attachment points (muzzle, shell drop, camera...): hidden
ROOT_COLOR = (1.0, 0.75, 0.1)
PART_COLOR = (0.2, 0.75, 1.0)
PIECE_COLOR = (1.0, 0.35, 0.6)  # sight and pendant holders
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
GRIP_PROP = "st_grip"  # weapon rig toggle: in the right hand (trigger) or not
GRIP_CON = "ST Right Hand"
# left hand support, removed: only cleaned up from rigs connected by an older version
OLD_SUPPORT_PROP, OLD_SUPPORT_CON, OLD_SUPPORT, LEFT_IK = "st_support", "ST Mano izquierda", "Soporte", "hand_ik.L"
RIGHT_HAND = "DEF-hand.R"
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


def hold_pose(context, arm, rig):
    """A starting pose when the right arm is untouched: its IK hand moved so the weapon is held like the
    game's idle (low ready). An arm already posed is left alone."""
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
    """Remove the weapon's hand constraints, on itself and on the rig it was connected to: the weapon
    goes back to where it was before connecting, the left hand control stays where it is."""
    c = arm.constraints.get(GRIP_CON)
    if c:
        arm.constraints.remove(c)
    rig = arm.get("st_hand_rig")
    pb = rig.pose.bones.get(LEFT_IK) if isinstance(rig, bpy.types.Object) else None
    for name in (OLD_SUPPORT_CON, LEFT_CON):
        con = pb.constraints.get(name) if pb else None
        if con:
            keep = rig.matrix_world @ pb.matrix
            pb.constraints.remove(con)
            pb.matrix = rig.matrix_world.inverted() @ keep
    for prop in (LEFT_PROP, "st_hand_rig"):
        if prop in arm:
            del arm[prop]


def connected(arm):
    """The character rig the weapon is in the hand of, or None."""
    rig = arm.get("st_hand_rig")
    return rig if isinstance(rig, bpy.types.Object) and arm.constraints.get(GRIP_CON) else None


def character_rig(ob):
    """The character rig of a clicked or selected object (its mesh, its rig or something parented to
    it), if it has the hands a weapon goes to."""
    while ob:
        rig = ob if ob.type == "ARMATURE" else ob.find_armature() if ob.type == "MESH" else None
        if rig and not weapon_rig(rig) and RIGHT_HAND in rig.data.bones:
            return rig
        ob = ob.parent
    return None


def connect(context, arm, rig):
    """Weapon in the right hand of `rig`: it follows the hand, with an animatable toggle on the weapon rig."""
    disconnect(arm)
    if GRIP_PROP not in arm:
        arm[GRIP_PROP] = True
        arm.id_properties_ui(GRIP_PROP).update(description=tip_("The weapon follows the character's right hand (trigger)"))
    if OLD_SUPPORT_PROP in arm:
        del arm[OLD_SUPPORT_PROP]
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
    if OLD_SUPPORT in arm.data.bones:  # from an older version
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = arm
        arm.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        arm.data.edit_bones.remove(arm.data.edit_bones[OLD_SUPPORT])
        bpy.ops.object.mode_set(mode="OBJECT")
    arm["st_hand_rig"] = rig
    # light it like the character, so it matches the hand
    host = next((m for m in bpy.data.objects if m.type == "MESH" and m.find_armature() == rig
                 and m.get("st_light") and not m.get("st_paper")), None)
    meshes = shaded_meshes(arm)
    if meshes:
        shading.light_weapon(meshes, host)
    return host


def shaded_meshes(arm):
    return [m for m in bpy.data.objects if m.type == "MESH" and m.get("st_weapon") and weapon_rig(m) == arm]


# ---------- left hand: a grip that slides along the weapon ----------
SLIDER, SLIDER_GUIDE = "ST Grip", "ST Grip Guide"  # weapon bones: the left hand's grip and its track
LEFT_PROP, LEFT_CON = "st_left", "ST Left Hand (Grip)"
LEFT_HAND, LEFT_ARM = "DEF-hand.L", "upper_arm_parent.L"
SLIDE_FROM, SLIDE_TO = 0.08, 0.45  # track: from 8 cm ahead of the grip to 45% of the way to the muzzle
SLIDE_AT = 0.3  # where the grip starts, as a share of the way to the muzzle
SLIDER_COLOR = (0.35, 1.0, 0.4)


def body_mesh(arm):
    """The weapon's body: its biggest mesh (not the sight or a pendant hanging below)."""
    meshes = [m for m in arm.children if m.type == "MESH" and m.find_armature() == arm and not m.name.startswith("WGT")]
    return max(meshes, key=lambda m: len(m.data.vertices), default=None)


def ensure_slider(context, arm):
    """The Agarre bone: it slides along the barrel (Limit Location on its own Y, the barrel's axis)
    and sticks to the underside of the weapon (Shrinkwrap projecting up onto the body mesh), with a
    fixed guide bone showing its track. Weapon armature space: barrel toward -Y, top +Z."""
    if SLIDER in arm.data.bones:
        return True
    body = body_mesh(arm)
    if not body or "Root" not in arm.data.bones:
        return False
    to_arm = arm.matrix_world.inverted() @ body.matrix_world
    pts = [to_arm @ v.co for v in body.data.vertices]
    root = arm.data.bones["Root"].head_local
    muzzle = min(p.y for p in pts)
    start = root.y - SLIDE_FROM
    length = max(0.02, (root.y - muzzle) * SLIDE_TO - SLIDE_FROM)
    below = min(p.z for p in pts) - 0.03  # under the weapon: the shrinkwrap projects up onto its underside
    for o in context.view_layer.objects:
        o.select_set(False)
    context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for name in (SLIDER, SLIDER_GUIDE):
        b = eb.new(name)
        b.head, b.tail = Vector((root.x, start, below)), Vector((root.x, start - 0.05, below))  # local Y = toward the muzzle
        b.align_roll(Vector((0, 0, 1)))  # local Z = the weapon's top
        b.parent, b.use_deform = eb["Root"], False
    bpy.ops.object.mode_set(mode="OBJECT")
    pb = arm.pose.bones[SLIDER]
    lim = pb.constraints.new("LIMIT_LOCATION")
    lim.owner_space = "LOCAL"
    lim.use_min_x = lim.use_max_x = lim.use_min_y = lim.use_max_y = lim.use_min_z = lim.use_max_z = True
    lim.max_y, lim.use_transform_limit = length, True
    sw = pb.constraints.new("SHRINKWRAP")
    sw.target, sw.shrinkwrap_type = body, "PROJECT"
    sw.project_axis, sw.project_axis_space = "POS_Z", "LOCAL"
    pb.lock_location = (True, False, True)
    pb.location.y = min(max((root.y - muzzle) * SLIDE_AT - SLIDE_FROM, 0.0), length)  # along its track
    coll = arm.data.collections.get(CONTROLS) or arm.data.collections.new(CONTROLS)
    n = 24
    ring = _shape("WGT-ST_weapon_slider", [(math.cos(math.tau * i / n), 0, math.sin(math.tau * i / n)) for i in range(n)],
                  [(i, (i + 1) % n) for i in range(n)])
    track = _shape("WGT-ST_weapon_track", [(0, 0, 0), (0, 1, 0), (-1, 0, 0), (1, 0, 0), (-1, 1, 0), (1, 1, 0)],
                   [(0, 1), (2, 3), (4, 5)])
    for name, shape, scale, trans in ((SLIDER, ring, (0.03,) * 3, (0, 0, 0.03)), (SLIDER_GUIDE, track, (0.02, length, 1), (0, 0, 0))):
        p = arm.pose.bones[name]
        for c in list(p.bone.collections):
            c.unassign(p.bone)
        coll.assign(p.bone)
        p.custom_shape, p.use_custom_shape_bone_size = shape, False
        p.custom_shape_scale_xyz, p.custom_shape_translation = scale, trans
        common.paint(arm, name, SLIDER_COLOR)
    guide = arm.pose.bones[SLIDER_GUIDE]
    guide.bone.hide_select = True  # only shows the track: clicks go to the grip
    guide.lock_location = guide.lock_rotation = guide.lock_scale = (True, True, True)
    return True


def connect_left(context, arm, rig):
    """The left hand on the Agarre bone: the arm goes to IK, its hand control is placed on the grip
    (palm on it, fingers along the barrel, thumb up) and hung from it with a Child Of. The hand control
    still moves and turns to adjust the hold, relative to the grip; sliding the grip carries the hand."""
    pb = rig.pose.bones.get(LEFT_IK)
    if not pb or LEFT_HAND not in rig.data.bones or not ensure_slider(context, arm):
        return False
    old = pb.constraints.get(LEFT_CON)
    if old:
        pb.constraints.remove(old)
    if LEFT_PROP not in arm:
        arm[LEFT_PROP] = True
        arm.id_properties_ui(LEFT_PROP).update(description=tip_("The character's left hand goes to the weapon's grip"))
        arm.update_tag()
    if LEFT_ARM in rig.pose.bones and "IK_FK" in rig.pose.bones[LEFT_ARM]:
        rig.pose.bones[LEFT_ARM]["IK_FK"] = 0.0
    # the hand control on the grip, by the same rule as the right hand (palm on it, fingers along the
    # barrel, thumb up)...
    context.view_layer.update()
    grip = arm.matrix_world @ arm.pose.bones[SLIDER].matrix  # after its Limit Location and Shrinkwrap
    hand = rig.data.bones[LEFT_HAND]
    want = Matrix.Translation(grip.translation) @ arm.matrix_world.to_3x3().normalized().to_4x4()         @ grip_frame(rig, LEFT_HAND).inverted() @ hand.matrix_local
    pb.matrix = rig.matrix_world.inverted() @ want @ hand.matrix_local.inverted() @ pb.bone.matrix_local
    context.view_layer.update()
    # ...then hung from it keeping where it is: Blender's own Set Inverse (a hand-made inverse broke
    # with the rig away from the world origin)
    c = pb.constraints.new("CHILD_OF")
    c.name, c.target, c.subtarget = LEFT_CON, arm, SLIDER
    for o in context.view_layer.objects:
        o.select_set(False)
    context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    rig.data.bones.active = pb.bone
    with context.temp_override(active_object=rig, object=rig, active_pose_bone=pb):
        bpy.ops.constraint.childof_set_inverse(constraint=LEFT_CON, owner="BONE")
    bpy.ops.object.mode_set(mode="OBJECT")
    drive_influence(c, arm, LEFT_PROP)
    arm["st_hand_rig"] = rig
    return True


class STRINOVA_OT_weapon_left_hand(bpy.types.Operator):
    bl_idname = "strinova.weapon_left_hand"
    bl_label = "Connect left hand"
    bl_description = ("Puts the character's left hand on the weapon's grip (a green control that slides along "
                      "the barrel). The hand control still adjusts how it rests")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = weapon_rig(context.active_object)
        return arm is not None and connected(arm) is not None

    def execute(self, context):
        arm = weapon_rig(context.active_object)
        rig = connected(arm)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not connect_left(context, arm, rig):
            self.report({"ERROR"}, rpt_("Could not create the grip on this weapon"))
            return {"CANCELLED"}
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = arm
        arm.select_set(True)
        self.report({"INFO"}, rpt_("Left hand of {} on the grip of {}").format(rig.name, arm.name))
        return {"FINISHED"}


class STRINOVA_OT_weapon_hand(bpy.types.Operator):
    bl_idname = "strinova.weapon_hand"
    bl_label = "Connect weapon"
    bl_description = ("With the weapon selected: click a character in the viewport and the weapon goes to its "
                      "right hand (trigger). Esc or right click cancels")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return weapon_rig(context.active_object) is not None

    def finish(self, context, arm, rig):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        host = connect(context, arm, rig)
        for o in context.view_layer.objects:  # the weapon stays selected: the panel shows its hands
            o.select_set(False)
        context.view_layer.objects.active = arm
        arm.select_set(True)
        self.report({"INFO"}, rpt_("{} in the hand of {}").format(arm.name, rig.name)
                    + (rpt_(", lit by {}").format(host.name) if host else ""))
        return {"FINISHED"}

    def execute(self, context):  # scripts: the weapon and the character selected
        sel = list(context.selected_objects) + [context.active_object]
        arm = next((weapon_rig(o) for o in sel if o and weapon_rig(o)), None)
        rig = next((character_rig(o) for o in sel if o and not weapon_rig(o) and character_rig(o)), None)
        if not arm or not rig:
            self.report({"ERROR"}, rpt_("Select the weapon and the character (its rig or its mesh) together"))
            return {"CANCELLED"}
        return self.finish(context, arm, rig)

    def invoke(self, context, event):
        self.arm = weapon_rig(context.active_object)
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(iface_("Click the character that will hold the weapon  |  Esc / right click: cancel"))
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def end(self, context):
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)

    def pick(self, context, event):
        """The character under the mouse in any 3D viewport: a ray through the scene, past the weapon."""
        for area in context.window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if not region or not (region.x <= event.mouse_x < region.x + region.width
                                  and region.y <= event.mouse_y < region.y + region.height):
                continue
            rv3d = area.spaces.active.region_3d
            xy = (event.mouse_x - region.x, event.mouse_y - region.y)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
            dg = context.evaluated_depsgraph_get()
            for _ in range(16):  # skip the weapon and whatever is not a character
                hit, loc, _n, _i, ob, _m = context.scene.ray_cast(dg, origin, direction)
                if not hit:
                    return None
                rig = character_rig(ob) if not weapon_rig(ob) else None
                if rig:
                    return rig
                origin = loc + direction * 1e-4
        return None

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.end(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            rig = self.pick(context, event)
            if not rig:
                self.report({"WARNING"}, rpt_("No rigged character there: click on its mesh"))
                return {"RUNNING_MODAL"}
            self.end(context)
            return self.finish(context, self.arm, rig)
        return {"PASS_THROUGH"}  # navigate the view meanwhile


class STRINOVA_OT_weapon_release(bpy.types.Operator):
    bl_idname = "strinova.weapon_release"
    bl_label = "Disconnect weapon"
    bl_description = "Releases the weapon from the character's hands: it goes back to where it was before connecting"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = weapon_rig(context.active_object)
        return arm is not None and connected(arm) is not None

    def execute(self, context):
        arm = weapon_rig(context.active_object)
        rig = connected(arm)
        disconnect(arm)
        meshes = shaded_meshes(arm)
        if meshes:
            shading.light_weapon(meshes)  # its own light again
        self.report({"INFO"}, rpt_("{} out of the hand of {}").format(arm.name, rig.name))
        return {"FINISHED"}


class STRINOVA_OT_import_weapon(bpy.types.Operator, ImportHelper):
    bl_idname = "strinova.import_weapon"
    bl_label = "Import weapon"
    bl_description = ("Imports a weapon (.uemodel or .fbx) into its own collection. With the weapon's body or the "
                      "skin folder, it also brings its sight and pendant and puts them in place")
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(default="*.uemodel;*.fbx", options={"HIDDEN"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    sight: bpy.props.BoolProperty(name="Include sight", default=True,
                                  description="Brings the weapon's sight and puts it in place; without it, only the body")

    def invoke(self, context, event):
        common.browse_from_root(self, context)
        return super().invoke(context, event)

    def execute(self, context):
        path = self.filepath
        if not os.path.isfile(path):  # no file picked: the skin folder the browser shows
            path = next((d for d in (path, self.directory, os.path.dirname(path)) if d and os.path.isdir(d)), "")
        files = assembly(path, self.sight) if path else []
        if not files:
            self.report({"ERROR"}, rpt_("Pick the weapon (.uemodel or .fbx) or the folder of one of its skins"))
            return {"CANCELLED"}
        # a character (its 3D and paper models live in Mesh3D* / Mesh2D) picked here by mistake: as a
        # weapon it got weapon shading and showed only its outline
        if any(re.match(r"mesh[23]d", part, re.I) for f in files for part in os.path.normpath(f).split(os.sep)):
            self.report({"ERROR"}, rpt_("That is a character, not a weapon: use Import character"))
            return {"CANCELLED"}
        if any(f.lower().endswith(".uemodel") for f in files) and not hasattr(bpy.types, "UF_OT_import_uemodel"):
            self.report({"ERROR"}, rpt_("UEFormat is not enabled: enable it or import the weapon as .fbx"))
            return {"CANCELLED"}
        common.remember_fmodel(files[0])
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        # own collection, active while importing, like a character (see importer.execute)
        vl = context.view_layer
        prev_active = vl.active_layer_collection
        coll = bpy.data.collections.new(f"Weapon {weapon_name(files[0])}")
        context.scene.collection.children.link(coll)
        vl.active_layer_collection = importer._layer_collection(vl.layer_collection, coll)
        before, before_colls = set(bpy.data.objects), set(bpy.data.collections)
        hung, pieces, controls = [], {}, 0
        try:
            body = import_file(files[0])
            body_arm = next((o for o in body if o.type == "ARMATURE"), None)
            for f in files[1:]:
                kind = piece_of(f)[0]
                if kind == "magazine" and carries(body, PIECE_BONE[kind]):
                    continue  # the body has its own (the loose one is for the reload animation)
                objs = import_file(f)
                if body_arm and objs and hang(context, objs, body_arm, PIECE_BONE[kind]):
                    hung.append(kind)
                    meshes_k = [o for o in objs if o.type == "MESH"]
                    label = join_piece(context, body_arm, objs, PIECE_BONE[kind], PIECE_LABEL[kind])
                    pieces.setdefault(label or PIECE_BONE[kind], []).extend(meshes_k)
            if body_arm:
                controls = rig_weapon(context, body_arm, [o for o in body if o.type == "MESH"] + sum(pieces.values(), []), pieces)
                if ensure_slider(context, body_arm):
                    controls += 1
        finally:
            importer.gather_leftovers(context, coll, before, before_colls)
            vl.active_layer_collection = prev_active
        new = [o for o in bpy.data.objects if o not in before and not o.name.startswith("WGT-")]  # not the control shapes
        if not new:
            bpy.data.collections.remove(coll)
            self.report({"ERROR"}, rpt_("The file has no model"))
            return {"CANCELLED"}
        for o in vl.objects:
            o.select_set(False)
        meshes = [o for o in new if o.type == "MESH"]
        shaded, miss = "", []
        if meshes and context.scene.strinova_do_shading:
            root = assets_root(files[0], context.scene.strinova_char_dir, meshes)
            if root:
                report = shading.shade_weapon(context, meshes, root)
                for k, v in report.items():
                    print(f"[Strinova] {k}: {v}")
                done = sum(isinstance(v, dict) for v in report.values())
                shaded = rpt_(", {}/{} materials").format(done, len(report))
                miss = shading.missing_textures(report)
                if miss:
                    shaded += rpt_(" | {} materials without textures: not found in {}").format(len(miss), root)
            else:
                shaded = rpt_(", no shading: FModel's SkinAssets folder not found (set it in the add-on's preferences)")
        for o in meshes:
            o.select_set(True)
        vl.objects.active = meshes[0] if meshes else new[0]
        extra = rpt_(", with {}").format(rpt_(" and ").join(rpt_(k) for k in hung)) if hung else ""
        self.report({"WARNING" if miss else "INFO"}, rpt_("{}: {} mesh(es){}, {} controls{}").format(coll.name, len(meshes), extra, controls, shaded))
        return {"FINISHED"}


classes = (STRINOVA_OT_import_weapon, STRINOVA_OT_weapon_hand, STRINOVA_OT_weapon_left_hand, STRINOVA_OT_weapon_release)
