"""Helpers shared by several modules."""
# UI text is written in English; i18n.py translates it (Blender > Preferences > Interface > Language)
import os
import bpy
from bpy.app.translations import pgettext_iface as iface_, pgettext_tip as tip_, pgettext_rpt as rpt_


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def skin_assets(path):
    """FModel's SkinAssets folder in `path` (a file or folder inside it, or a folder above it), or None."""
    if not path:
        return None
    path = os.path.normpath(bpy.path.abspath(path))
    parts = path.split(os.sep)
    if "SkinAssets" in parts:
        return os.sep.join(parts[: parts.index("SkinAssets") + 1])
    for d, dirs, _ in os.walk(path):  # a folder above it (Output\Exports...): a few levels down at most
        if "SkinAssets" in dirs:
            return os.path.join(d, "SkinAssets")
        if d[len(path):].count(os.sep) >= 5:
            dirs.clear()
    return None


def browse_from_root(op, context):
    """Open an import's file browser in the panel's Root folder (else it opens wherever it was last,
    often the desktop)."""
    root = bpy.path.abspath(context.scene.strinova_char_dir)
    if root and os.path.isdir(root):
        op.filepath = os.path.join(root, "")  # trailing separator: a folder, no file picked


def fmodel_root():
    """SkinAssets of the FModel export in the add-on's preferences, or None."""
    p = _prefs()
    return skin_assets(p.fmodel_dir) if p else None


def remember_fmodel(path):
    """Keep the FModel export a model was imported from in the preferences (once per PC), so models kept
    elsewhere (an .fbx, a weapon) still find the game's textures."""
    p, root = _prefs(), skin_assets(path) if path and "SkinAssets" in os.path.normpath(path).split(os.sep) else None
    if p and root and fmodel_root() != root:
        p.fmodel_dir = root
        bpy.context.preferences.is_dirty = True  # saved with the preferences (auto-save, or Save Preferences)


def target_mesh(context):
    """The character mesh: the active mesh, or the skinned mesh of the active armature."""
    ob = context.active_object
    if ob and ob.type == "ARMATURE":  # allow selecting the skeleton too
        meshes = [c for c in ob.children if c.type == "MESH" and c.find_armature() == ob]
        ob = next((c for c in meshes if not c.get("st_paper")), meshes[0] if meshes else None)  # 3D over paper
    return ob if ob and ob.type == "MESH" else None


def drive_modifier(mod, rig, prop, expr, default, description):
    """Switch `mod` on and off (viewport and render) from the animatable rig[prop]; `expr` reads it
    as `v`. Used to hide meshes or pieces: hide_viewport can't be driven, since Blender stops
    evaluating an object hidden that way and the driver could never show it again."""
    if prop not in rig:
        rig[prop] = default
        rig.id_properties_ui(prop).update(description=description)
        rig.update_tag()  # the evaluated rig must get the new property, or the drivers read nothing and go invalid
    for path in ("show_viewport", "show_render"):
        mod.driver_remove(path)
        d = mod.driver_add(path).driver
        d.type = "SCRIPTED"
        v = d.variables.new()
        v.name, v.type = "v", "SINGLE_PROP"
        v.targets[0].id, v.targets[0].data_path = rig, f'["{prop}"]'
        d.expression = expr  # last: setting it clears the "invalid" flag a too-early evaluation leaves


def paint(rig, name, rgb, select=None):
    """Bone colour in edit and pose mode (the pose colour overrides Gacha's); white when active."""
    for c in (rig.data.bones[name].color, rig.pose.bones[name].color):
        c.palette = "CUSTOM"
        c.custom.normal = rgb
        c.custom.select = select or [min(1.0, v + 0.35) for v in rgb]
        c.custom.active = (1.0, 1.0, 1.0)
