"""Import: .uemodel (UEFormat) or .fbx, find the character's texture folder, then optionally run the
shading and rig operators (through bpy.ops)."""
import bpy, os, re, glob
from bpy_extras.io_utils import ImportHelper
from . import paper, shading, common
from .common import rpt_


def char_dir_from(path, mesh=None, current=""):
    """The folder the shading takes textures and material JSONs from, for a model at `path`."""
    # FModel layout: .../Characters/<Name>/<Skin>/Mesh3D/SK_*.uemodel
    parts = os.path.normpath(path).split(os.sep)
    if "Characters" in parts and parts.index("Characters") + 1 < len(parts) - 1:
        return os.sep.join(parts[: parts.index("Characters") + 2])
    # anywhere else: the model's own folder first, then up (an FBX next to its textures, or in a tree
    # beside them), so nothing has to be set in the panel beforehand
    found = shading.texture_root(path, shading.texture_names(mesh) if mesh else set())
    if found:
        return found
    # FBX kept outside the FModel export in a <Name>/<Skin>/... tree: textures and material JSONs
    # stay in FModel's export, so take <Name>'s folder next to the one already set in the panel, or in
    # the FModel export remembered in the preferences
    fm = common.fmodel_root()
    roots = [os.path.dirname(os.path.normpath(current)) if current else "", os.path.join(fm, "Characters") if fm else ""]
    for chars_root in filter(None, roots):
        for p in reversed(parts[1:-1]):  # not the drive: join(root, "D:") is "D:"
            if os.path.isdir(os.path.join(chars_root, p)):
                return os.path.join(chars_root, p)
    if not (current and os.path.isdir(bpy.path.abspath(current))):
        return os.path.dirname(path)  # no textures anywhere near: the shading reports them missing
    return None  # keep the folder already set in the panel


def skin_folder(path):
    """The model's skin folder: 'S001' in FModel's export, or the folder holding Mesh2D/Mesh3D* in an
    FBX tree renamed by skin name (fbx/Kanami/Ruiseñor/Mesh3D/...). None if neither."""
    parts = os.path.normpath(path).split(os.sep)
    s = next((p for p in reversed(parts) if re.fullmatch(r"S\d{3}", p)), None)
    return s or next((parts[i - 1] for i in range(len(parts) - 1, 0, -1) if re.match(r"Mesh[23]D", parts[i])), None)


def paper_path(path, char_dir):
    """The skin's paper model: in <skin>\\Mesh2D next to the 3D model's folder (FModel export or an FBX
    tree like it), else in FModel's export. Names vary (_PPM_, _PMM_, _skin), so any model there."""
    skin = skin_folder(path)
    dirs = [os.path.join(os.path.dirname(os.path.dirname(path)), "Mesh2D")]
    if skin and char_dir:
        dirs.append(os.path.join(char_dir, skin, "Mesh2D"))
    return next(filter(None, (first_model(d, recursive=True) for d in dirs)), None)


def first_model(folder, recursive=False):
    pattern = os.path.join(folder, "**" if recursive else "", "*.{}")
    found = sorted(f for ext in ("fbx", "uemodel") for f in glob.glob(pattern.format(ext), recursive=recursive))
    return found[0] if found else None


def models_in(folder):
    """(3D model, paper model) of a skin folder, or of one of its Mesh* folders. The lobby model
    (Mesh3DLobby, also spelled Mesh3DLobbby / Mesh3D_Lobby...) goes first: it carries the expressions."""
    folder = os.path.normpath(folder)
    if re.match(r"(?i)mesh[23]d", os.path.basename(folder)):
        folder = os.path.dirname(folder)
    subs = sorted((d for d in os.listdir(folder) if re.match(r"(?i)mesh3d", d) and os.path.isdir(os.path.join(folder, d))),
                  key=lambda d: not re.search(r"(?i)lo", d[6:]))
    model = next(filter(None, (first_model(os.path.join(folder, d)) for d in subs)), None)
    return model, first_model(os.path.join(folder, "Mesh2D"), recursive=True)


def collection_name(path):
    """'<Character> <Skin>' from a <Character>/<Skin>/Mesh* path (e.g. 'Flavia S001', 'Kanami Ruiseñor'),
    else the file name."""
    parts = os.path.normpath(path).split(os.sep)
    i = next((i for i in range(len(parts) - 1, 2, -1) if re.match(r"(?i)mesh[23]d", parts[i])), None)  # >= 3: not a drive
    if not i:
        return os.path.splitext(os.path.basename(path))[0]
    return f"{parts[i - 2]} {skin_folder(path) or parts[i - 1]}"


def _layer_collection(lc, coll):
    if lc.collection == coll:
        return lc
    for child in lc.children:
        found = _layer_collection(child, coll)
        if found:
            return found
    return None


def _subtree(coll):
    out = {coll}
    for child in coll.children:
        out |= _subtree(child)
    return out


def gather_leftovers(context, coll, before_objs, before_colls):
    """Move into `coll` whatever the import created outside it (ST_Light and panel labels land in
    the scene root; a stray new collection). Moved collections keep their view-layer state."""
    sc, vl = context.scene, context.view_layer
    inside = _subtree(coll)
    for c in [c for c in bpy.data.collections if c not in before_colls and c not in inside]:
        if any(c.name in p.children for p in bpy.data.collections if p not in before_colls and p != c):
            continue  # nested in another new collection: it moves with its parent
        lc = _layer_collection(vl.layer_collection, c)
        state = (lc.exclude, lc.hide_viewport) if lc else None
        for parent in [sc.collection] + list(bpy.data.collections):
            if parent != coll and c.name in parent.children:
                parent.children.unlink(c)
        coll.children.link(c)
        lc = _layer_collection(vl.layer_collection, c)
        if lc and state:
            lc.exclude, lc.hide_viewport = state
    inside = _subtree(coll)
    for o in bpy.data.objects:
        if o in before_objs:
            continue
        outside = [c for c in o.users_collection if c not in inside]
        if outside and not any(c in inside for c in o.users_collection):
            coll.objects.link(o)
        for c in outside:
            c.objects.unlink(o)


class STRINOVA_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "strinova.import_character"
    bl_label = "Import character"
    bl_description = ("Imports a character .uemodel (UEFormat) or .fbx and optionally applies shading and rig. "
                      "With a skin folder (no file picked) it imports its 3D model and its paper version")
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(default="*.uemodel;*.fbx", options={"HIDDEN"})
    # the file browser fills it with the folder it shows: used when no file is picked
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    do_shading: bpy.props.BoolProperty(name="Apply Toon Shading", default=True)
    do_rig: bpy.props.BoolProperty(name="Generate rig", default=True)
    do_paper: bpy.props.BoolProperty(name="Include paper version", default=False)
    # the paper version's second import: the exact collection of the 3D import it joins (by name a
    # repeated skin would find the first copy, "Name" vs "Name.001")
    collection: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        # the panel's checkboxes; the file browser's own options sidebar is easy to miss
        sc = context.scene
        self.do_shading, self.do_rig, self.do_paper = sc.strinova_do_shading, sc.strinova_do_rig, sc.strinova_do_paper
        return super().invoke(context, event)

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            # no file picked: the browser sends its folder, sometimes with leftover text from the name field
            folder = next((d for d in (self.filepath, self.directory, os.path.dirname(self.filepath)) if d and os.path.isdir(d)), None)
            print(f"[Strinova] sin archivo: filepath={self.filepath!r} directory={self.directory!r} -> {folder!r}")
            if not folder:
                self.report({"ERROR"}, rpt_("Not found: {}").format(self.filepath))
                return {"CANCELLED"}
            self.filepath = folder
        if os.path.isdir(self.filepath):  # a skin folder: its 3D model (lobby first) and its paper version
            model, paper_model = models_in(self.filepath)
            if not (model or paper_model):
                self.report({"ERROR"}, rpt_("The folder has no Mesh3D or Mesh2D with an .fbx or .uemodel"))
                return {"CANCELLED"}
            self.filepath, self.do_paper = model or paper_model, bool(model and paper_model)
        ext = os.path.splitext(self.filepath)[1].lower()
        # hasattr(bpy.ops.uf, ...) is always True, so check the registered operator type instead
        if ext == ".uemodel" and not hasattr(bpy.types, "UF_OT_import_uemodel"):
            self.report({"ERROR"}, rpt_("UEFormat is not enabled: enable it or import the character as .fbx"))
            return {"CANCELLED"}
        if ext not in (".uemodel", ".fbx"):
            self.report({"ERROR"}, rpt_("Unsupported format, use .uemodel or .fbx"))
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        common.remember_fmodel(self.filepath)
        # One collection per character, active for the whole import: UEFormat imports into the active
        # collection and Gacha Setup's rigger names the rig after it and puts its objects and its
        # WGTS_* (control shapes) collection there, so everything lands together.
        vl = context.view_layer
        prev_active = vl.active_layer_collection
        name = collection_name(self.filepath)
        # paper version (Mesh2D) of a character already in the scene: joins its collection and rig
        existing = bpy.data.collections.get(self.collection or name)
        if existing and not _layer_collection(vl.layer_collection, existing):
            existing = None  # same name but not in this scene
        host = paper.find_host(existing) if paper.is_paper_path(self.filepath) else None
        if host:
            coll = existing
        else:
            coll = bpy.data.collections.new(name)
            context.scene.collection.children.link(coll)
        own = coll.name  # "Name.001" when the skin is already in the scene
        vl.active_layer_collection = _layer_collection(vl.layer_collection, coll)
        before = set(bpy.data.objects)
        before_colls = set(bpy.data.collections)
        try:
            result = self._import(context, ext, coll, before, host)
        finally:
            gather_leftovers(context, coll, before, before_colls)
            vl.active_layer_collection = prev_active
            if not coll.objects and not coll.children:  # nothing imported
                bpy.data.collections.remove(coll)
            elif coll.name != own and own not in bpy.data.collections:
                coll.name = own  # Gacha's rigger renames the active collection to the bare character name
        if result == {"FINISHED"} and self.do_paper and not paper.is_paper_path(self.filepath):
            pp = paper_path(self.filepath, context.scene.strinova_char_dir)
            if pp:  # a second import: it finds this character in its collection and joins its rig
                bpy.ops.strinova.import_character(filepath=pp, do_shading=self.do_shading, do_rig=False, do_paper=False,
                                                  collection=coll.name)
            else:
                self.report({"WARNING"}, rpt_("{}: this skin has no paper version (Mesh2D)").format(name))
        return result

    def _import(self, context, ext, coll, before, host=None):
        if ext == ".fbx":
            # leaf bones are the *_end tips Blender adds on FBX export; they are not part of the game skeleton
            bpy.ops.import_scene.fbx(filepath=self.filepath, ignore_leaf_bones=True)
        else:
            d, f = os.path.split(self.filepath)
            bpy.ops.uf.import_uemodel(filepath=self.filepath, directory=d, files=[{"name": f}])
        mesh = next((o for o in bpy.data.objects if o not in before and o.type == "MESH" and o.find_armature()), None)
        if not mesh:
            self.report({"ERROR"}, rpt_("The file has no mesh with a skeleton"))
            return {"CANCELLED"}
        # after the import: the search looks for the textures this model's materials name
        char_dir = char_dir_from(self.filepath, mesh, context.scene.strinova_char_dir)
        if char_dir:
            context.scene.strinova_char_dir = char_dir
        elif self.do_shading:
            print(f"[Strinova] {os.path.basename(self.filepath)} esta fuera de la exportacion de FModel; "
                  f"se usa la carpeta del panel: {context.scene.strinova_char_dir}")
        mesh["st_source"] = self.filepath  # the shading prefers textures from this model's own skin folder
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = mesh
        mesh.select_set(True)
        done, failed = [rpt_("imported")], []
        do_rig = self.do_rig
        if host:  # before the shading, so it reuses the host's sun, head empties and lighting panel
            unmapped = paper.attach(context, mesh, host)
            done.append(rpt_("paper on {}").format(host.find_armature().name))
            do_rig = False
            if unmapped:
                print(f"[Strinova] papel: grupos sin hueso en el rig: {unmapped}")
        elif paper.is_paper_path(self.filepath) and do_rig:
            print("[Strinova] version de papel sin su personaje 3D en la escena: se importa sin rig")
            do_rig = False
        steps = [("shading", self.do_shading, bpy.ops.strinova.setup_toon), ("rig", do_rig, bpy.ops.strinova.rig_physics)]
        for name, wanted, op in steps:
            if not wanted:
                continue
            context.view_layer.objects.active = mesh
            try:  # keep the imported model even if a later step fails on an unusual character
                op()
                done.append(name)
            except RuntimeError as e:
                print(f"[Strinova] {name} fallo: {e}")
                failed.append(name)
        if host:
            paper.ensure_switch(host.find_armature())
        msg = f"{mesh.name}: " + ", ".join(done) + (rpt_(" | failed: {} (see console)").format(", ".join(failed)) if failed else "")
        miss = mesh.get("st_missing_textures", 0) if "shading" in done else 0
        if miss:  # the shading's own warning scrolls away behind this message
            msg += rpt_(" | {} materials without textures: check the Character folder ({})").format(miss, context.scene.strinova_char_dir)
        # the match model (Mesh3D) usually has no facial expressions; the lobby one (Mesh3DLobby) has them
        no_face = not paper.is_paper_path(self.filepath) and not mesh.data.shape_keys
        if no_face:
            lobby = models_in(os.path.dirname(os.path.dirname(self.filepath)))[0]
            lobby = lobby if lobby and re.search(r"(?i)mesh3d.*lo", lobby) and os.path.normcase(lobby) != os.path.normcase(self.filepath) else None
            msg += (rpt_(" | no facial expressions in this model: import the lobby one, {}").format(lobby) if lobby
                    else rpt_(" | no facial expressions in this model (the lobby model, Mesh3DLobby, usually has them)"))
        self.report({"WARNING" if failed or miss or no_face else "INFO"}, msg)
        return {"FINISHED"}


classes = (STRINOVA_OT_import,)
