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
from mathutils import Matrix, Vector
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
    return controls


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


classes = (STRINOVA_OT_import_weapon,)
