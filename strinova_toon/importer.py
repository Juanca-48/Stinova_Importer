"""Import: .uemodel (UEFormat) or .fbx, detect the FModel character folder, then optionally run the
shading and rig operators (called through bpy.ops, so this module does not depend on them)."""
import bpy, os, re, glob
from bpy_extras.io_utils import ImportHelper
from . import paper


def char_dir_from(path, current=""):
    # FModel layout: .../Characters/<Name>/<Skin>/Mesh3D/SK_*.uemodel
    parts = os.path.normpath(path).split(os.sep)
    if "Characters" in parts and parts.index("Characters") + 1 < len(parts) - 1:
        return os.sep.join(parts[: parts.index("Characters") + 2])
    # FBX kept outside the FModel export in a <Name>/<Skin>/... tree: textures and material JSONs
    # stay in FModel's export, so take <Name>'s folder next to the one already set in the panel
    chars_root = os.path.dirname(os.path.normpath(current)) if current else ""
    for p in reversed(parts[:-1]):
        if chars_root and os.path.isdir(os.path.join(chars_root, p)):
            return os.path.join(chars_root, p)
    return None  # e.g. an FBX saved elsewhere: keep the folder already set in the panel


def skin_of(path):
    """'S001'-style skin folder in the path, or None."""
    return next((p for p in reversed(os.path.normpath(path).split(os.sep)) if re.fullmatch(r"S\d{3}", p)), None)


def paper_path(path, char_dir):
    """The skin's paper model: in <skin>\\Mesh2D next to the 3D model's folder (FModel export or an FBX
    tree like it), else in FModel's export. Names vary (_PPM_, _PMM_, _skin), so any model there."""
    skin = skin_of(path)
    dirs = [os.path.join(os.path.dirname(os.path.dirname(path)), "Mesh2D")]
    if skin and char_dir:
        dirs.append(os.path.join(char_dir, skin, "Mesh2D"))
    for d in dirs:
        found = sorted(f for ext in ("fbx", "uemodel") for f in glob.glob(os.path.join(d, "**", f"*.{ext}"), recursive=True))
        if found:
            return found[0]
    return None


def collection_name(path, char_dir):
    """'<Character> <Skin>' from the file path (e.g. 'Flavia S001'), else the file name."""
    skin = skin_of(path)
    char = os.path.basename(char_dir) if char_dir else None
    return " ".join(x for x in (char, skin) if x) or os.path.splitext(os.path.basename(path))[0]


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
    bl_label = "Importar personaje"
    bl_description = "Importa un .uemodel (UEFormat) o .fbx del personaje y opcionalmente aplica shading y rig"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(default="*.uemodel;*.fbx", options={"HIDDEN"})
    do_shading: bpy.props.BoolProperty(name="Aplicar Toon Shading", default=True)
    do_rig: bpy.props.BoolProperty(name="Generar rig", default=True)
    do_paper: bpy.props.BoolProperty(name="Incluir version de papel", default=False)

    def invoke(self, context, event):
        # the panel's checkboxes; the file browser's own options sidebar is easy to miss
        sc = context.scene
        self.do_shading, self.do_rig, self.do_paper = sc.strinova_do_shading, sc.strinova_do_rig, sc.strinova_do_paper
        return super().invoke(context, event)

    def execute(self, context):
        ext = os.path.splitext(self.filepath)[1].lower()
        # hasattr(bpy.ops.uf, ...) is always True, so check the registered operator type instead
        if ext == ".uemodel" and not hasattr(bpy.types, "UF_OT_import_uemodel"):
            self.report({"ERROR"}, "UEFormat no esta activo: activalo o importa el personaje como .fbx")
            return {"CANCELLED"}
        if ext not in (".uemodel", ".fbx"):
            self.report({"ERROR"}, "Formato no soportado, usa .uemodel o .fbx")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        char_dir = char_dir_from(self.filepath, context.scene.strinova_char_dir)
        # One collection per character, active for the whole import: UEFormat imports into the active
        # collection and Gacha Setup's rigger names the rig after it and puts its objects and its
        # WGTS_* (control shapes) collection there, so everything lands together.
        vl = context.view_layer
        prev_active = vl.active_layer_collection
        name = collection_name(self.filepath, char_dir)
        # paper version (Mesh2D) of a character already in the scene: joins its collection and rig
        existing = bpy.data.collections.get(name)
        if existing and not _layer_collection(vl.layer_collection, existing):
            existing = None  # same name but not in this scene
        host = paper.find_host(existing) if paper.is_paper_path(self.filepath) else None
        if host:
            coll = existing
        else:
            coll = bpy.data.collections.new(name)
            context.scene.collection.children.link(coll)
        vl.active_layer_collection = _layer_collection(vl.layer_collection, coll)
        before = set(bpy.data.objects)
        before_colls = set(bpy.data.collections)
        try:
            result = self._import(context, ext, char_dir, coll, before, host)
        finally:
            gather_leftovers(context, coll, before, before_colls)
            vl.active_layer_collection = prev_active
            if not coll.objects and not coll.children:  # nothing imported
                bpy.data.collections.remove(coll)
            elif name not in bpy.data.collections:
                coll.name = name  # Gacha's rigger renames the active collection to the bare character name
        if result == {"FINISHED"} and self.do_paper and not paper.is_paper_path(self.filepath):
            pp = paper_path(self.filepath, context.scene.strinova_char_dir)
            if pp:  # a second import: it finds this character in its collection and joins its rig
                bpy.ops.strinova.import_character(filepath=pp, do_shading=self.do_shading, do_rig=False, do_paper=False)
            else:
                self.report({"WARNING"}, f"{name}: esta skin no trae version de papel (Mesh2D)")
        return result

    def _import(self, context, ext, char_dir, coll, before, host=None):
        if ext == ".fbx":
            # leaf bones are the *_end tips Blender adds on FBX export; they are not part of the game skeleton
            bpy.ops.import_scene.fbx(filepath=self.filepath, ignore_leaf_bones=True)
        else:
            d, f = os.path.split(self.filepath)
            bpy.ops.uf.import_uemodel(filepath=self.filepath, directory=d, files=[{"name": f}])
        mesh = next((o for o in bpy.data.objects if o not in before and o.type == "MESH" and o.find_armature()), None)
        if not mesh:
            self.report({"ERROR"}, "El archivo no trae una malla con esqueleto")
            return {"CANCELLED"}
        if char_dir:
            context.scene.strinova_char_dir = char_dir
        elif self.do_shading:
            print(f"[Strinova] {os.path.basename(self.filepath)} esta fuera de la exportacion de FModel; "
                  f"se usa la carpeta del panel: {context.scene.strinova_char_dir}")
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = mesh
        mesh.select_set(True)
        done, failed = ["importado"], []
        do_rig = self.do_rig
        if host:  # before the shading, so it reuses the host's sun, head empties and lighting panel
            unmapped = paper.attach(context, mesh, host)
            done.append(f"papel en {host.find_armature().name}")
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
        msg = f"{mesh.name}: " + ", ".join(done) + (f" | fallo: {', '.join(failed)} (ver consola)" if failed else "")
        self.report({"WARNING" if failed else "INFO"}, msg)
        return {"FINISHED"}


classes = (STRINOVA_OT_import,)
