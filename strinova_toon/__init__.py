# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    "name": "Strinova Toon Setup",
    "author": "juanc",
    "version": (2, 0, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar (N) > Strinova",
    "description": "Imports Strinova characters (FModel) with toon shading, rig and constraint-based physics",
    "category": "Import-Export",
    "license": "GPL-3.0-or-later",
}

# Strinova (PaperMan) character setup, one module per concern: see the module list in INSTRUCCIONES.txt.
if "bpy" in locals():  # add-on reload: refresh the submodules too (import_module also loads new ones)
    import importlib
    for _n in ("common", "i18n", "shading", "own_textures", "effects", "face", "accessory", "rig", "paper", "importer", "weapon", "migrate", "viewport"):
        importlib.reload(importlib.import_module(f".{_n}", __package__))
from . import common, i18n, shading, face, accessory, rig, paper, importer, weapon, migrate, viewport
import bpy


class STRINOVA_PT_panel(bpy.types.Panel):
    bl_label = "Strinova Toon"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Strinova"

    def draw(self, context):
        col = self.layout.column()
        # for animating: renders don't change
        col.prop(context.scene, "strinova_fast_viewport", toggle=True, icon="PLAY")
        col.label(text="Root folder:")
        col.prop(context.scene, "strinova_char_dir", text="")
        col.separator()
        col.operator(importer.STRINOVA_OT_import.bl_idname, icon="IMPORT")
        opts = col.column(align=True)
        opts.prop(context.scene, "strinova_do_shading")
        opts.prop(context.scene, "strinova_do_rig")
        ik = opts.row(align=True)
        ik.active = context.scene.strinova_do_rig
        ik.prop(context.scene, "strinova_ik_mode", expand=True)
        opts.prop(context.scene, "strinova_do_paper")
        # weapons are imported apart: many are shared by several skins, and a skin never brings its weapon
        header, body = col.panel("strinova_weapons", default_closed=False)
        header.label(text="Weapons", icon="MOD_ARMATURE")
        if body:
            body.operator(weapon.STRINOVA_OT_import_weapon.bl_idname, icon="IMPORT")
            w = weapon.weapon_rig(context.active_object)
            if w:
                body.label(text=w.name, icon="ARMATURE_DATA")
                mesh = weapon.body_mesh(w)
                omod = mesh.modifiers.get("ST Outline") if mesh else None
                if omod and omod.node_group:
                    body.prop(shading.mod_input(omod, "Width"), "value", text="Outline width")
                holder = weapon.connected(w)
                if not holder:
                    body.operator(weapon.STRINOVA_OT_weapon_hand.bl_idname, icon="EYEDROPPER")
                else:
                    body.label(text=common.iface_("In the hand of {}").format(holder.name), icon="LINKED")
                    hands = body.column(align=True)
                    # animatable: keyframe to let go or take the weapon
                    hands.prop(w, f'["{weapon.GRIP_PROP}"]', text="Right hand (trigger)", toggle=True, icon="HAND")
                    hands.operator(weapon.STRINOVA_OT_weapon_left_hand.bl_idname, icon="VIEW_PAN")
                    if weapon.LEFT_PROP in w:
                        hands.prop(w, f'["{weapon.LEFT_PROP}"]', text="Left hand (grip)", toggle=True, icon="HAND")
                    body.operator(weapon.STRINOVA_OT_weapon_release.bl_idname, icon="UNLINKED")
        # shading and rig run inside the import; their operators stay registered for it (and F3)
        arm = rig.target_rig(context)
        if arm:
            # per-character settings under its name; collapsible, open/closed state remembered by Blender
            header, body = col.panel("strinova_physics", default_closed=False)
            header.label(text=arm.name, icon="ARMATURE_DATA")
            if body is None:
                return
            if paper.PAPER_PROP in arm:  # animatable: keyframe it to swap in one frame
                body.prop(arm, f'["{paper.PAPER_PROP}"]', text="Paper version", icon="FILE_IMAGE")
            shows = sorted(k for k in arm.keys() if k.startswith(accessory.SHOW))  # one per accessory
            for k in shows:
                label = k[len(accessory.SHOW):].removeprefix(accessory.PREFIX)
                if len(shows) == 1 and accessory.OWN_BONE.match(label):  # scenes up to 1.4 beta 2 may have one per mask bone
                    label = common.iface_("Mask")
                body.prop(arm, f'["{k}"]', text=common.iface_("Show {}").format(label), icon="HIDE_OFF")
        if arm and rig.PHYSICS_PROP in arm:
            body.separator()
            body.prop(arm, f'["{rig.PHYSICS_PROP}"]', text="Physics", text_ctxt=i18n.CTX)  # checkbox
            sliders = body.column()
            sliders.active = bool(arm[rig.PHYSICS_PROP])  # greyed out while physics is off
            for prop, _, label in rig.INERTIA_PROPS.values():
                if prop in arm:
                    sliders.prop(arm, f'["{prop}"]', text=label, slider=True)
        if not common.target_mesh(context):
            col.label(text="Select the mesh or its armature", icon="INFO")


class STRINOVA_PT_lighting(bpy.types.Panel):
    """Lighting of the selected character (its paper version and the weapon it holds follow it) or loose weapon."""
    bl_label = "Lighting"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Strinova"

    @staticmethod
    def character(context):
        """The mesh of the selected character, or None. Selected, not only active: an object stays active
        after it is deselected. A weapon in a hand follows its character's lighting: not shown."""
        ob = context.active_object
        mesh = common.target_mesh(context) if ob and ob.select_get() else None
        return mesh if mesh and not mesh.get("st_weapon_host") and (
            shading.lighting_source(mesh) or "ST Outline" in mesh.modifiers and not mesh.get("st_weapon")) else None

    @classmethod
    def poll(cls, context):
        return cls.character(context) is not None

    def draw(self, context):
        col = self.layout.column()
        mesh = self.character(context)
        src = shading.lighting_source(mesh)
        if src:
            col.label(text=src.name, icon="MESH_DATA")
            if not src.get("st_weapon"):  # weapons have no wheels
                col.label(text="Lighting Type:")
                col.row(align=True).prop(src, f'["{shading.LIGHTING_TYPE}"]', expand=True)
            if src[shading.LIGHTING_TYPE]:
                box = col.box().column()
                box.label(text="Custom Colors", icon="COLOR")
                for c in shading.COLORS:
                    box.label(text=common.iface_(shading.ui_name(c)) + ":")
                    box.prop(src, f'["st_{c}"]', text="")
            for prop, text in (("st_rim_scale", "Rim Scale"), ("st_rim_extra", "Extra Rim"), ("st_shadow_softness", "Shadow Softness"),
                               ("st_hair_shadow", "Hair Shadow")):
                if prop in src and not (prop == "st_hair_shadow" and src.get("st_weapon")):  # added in 1.4: older characters lack it
                    col.prop(src, f'["{prop}"]', text=text, slider=True)
        omod = mesh.modifiers.get("ST Outline")
        if omod and omod.node_group and not mesh.get("st_weapon"):  # a weapon's is in its own section
            col.prop(shading.mod_input(omod, "Width"), "value", text="Outline width")
            if not context.scene.strinova_fast_viewport:
                col.prop(omod, "show_viewport", text="Outline in viewport")  # off: faster playback; renders keep it


class STRINOVA_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    fmodel_dir: bpy.props.StringProperty(
        name="FModel export folder", subtype="DIR_PATH",
        description="FModel's export with the game's textures (the folder holding SkinAssets, or SkinAssets itself). "
                    "Filled in by itself the first time you import from it. Used when a model elsewhere (an .fbx, a "
                    "weapon) has no textures near it")

    def draw(self, context):
        self.layout.prop(self, "fmodel_dir")


classes = importer.classes + weapon.classes + shading.classes + rig.classes + (STRINOVA_PT_panel, STRINOVA_PT_lighting, STRINOVA_AddonPreferences)


def register():
    bpy.app.translations.register(__name__, i18n.translations)
    migrate.register()
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.strinova_do_shading = bpy.props.BoolProperty(
        name="Apply Toon Shading", default=True, description="Toon materials, lighting and outline on import")
    bpy.types.Scene.strinova_do_rig = bpy.props.BoolProperty(
        name="Generate rig", default=True, description="Rig with Gacha Setup, face, gaze and physics on import")
    bpy.types.Scene.strinova_ik_mode = bpy.props.EnumProperty(
        name="IK method", items=rig.IK_MODES, default="ROTATION",
        description="How the generated rig's arm and leg IK aims the elbows and knees")
    bpy.types.Scene.strinova_do_paper = bpy.props.BoolProperty(
        name="Include paper version", default=False,
        description="Also imports the skin's paper version (Mesh2D), joined to the 3D rig with its switch")
    bpy.types.Scene.strinova_fast_viewport = bpy.props.BoolProperty(
        name="Fast viewport", default=False, update=viewport.update,
        description="For animating: shows flat textures, without lighting, outline or effects, in the 3D views only. "
                    "Nothing is lost (colours, lights, keyframes) and renders don't change")
    bpy.types.Scene.strinova_char_dir = bpy.props.StringProperty(
        name="Root folder",
        subtype="DIR_PATH",
        description="Folder with the character's textures and material JSONs (FModel's Characters\\<Name>). "
                    "Filled on import from the model's path",
    )


def unregister():
    del bpy.types.Scene.strinova_fast_viewport
    del bpy.types.Scene.strinova_char_dir
    del bpy.types.Scene.strinova_do_shading
    del bpy.types.Scene.strinova_do_rig
    del bpy.types.Scene.strinova_ik_mode
    del bpy.types.Scene.strinova_do_paper
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    bpy.app.translations.unregister(__name__)
    migrate.unregister()
