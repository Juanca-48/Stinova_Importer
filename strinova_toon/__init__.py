bl_info = {
    "name": "Strinova Toon Setup",
    "author": "juanc",
    "version": (0, 3, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar (N) > Strinova",
    "description": "Importa personajes de Strinova (FModel) con toon shading, rig y fisica por constraints",
    "category": "Import-Export",
}

# Strinova (PaperMan) character setup, one module per concern: see the module list in INSTRUCCIONES.txt.
if "bpy" in locals():  # add-on reload: refresh the submodules too (import_module also loads new ones)
    import importlib
    for _n in ("common", "shading", "face", "accessory", "rig", "paper", "importer", "weapon"):
        importlib.reload(importlib.import_module(f".{_n}", __package__))
from . import common, shading, face, accessory, rig, paper, importer, weapon
import bpy


class STRINOVA_PT_panel(bpy.types.Panel):
    bl_label = "Strinova Toon"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Strinova"

    def draw(self, context):
        col = self.layout.column()
        col.operator(importer.STRINOVA_OT_import.bl_idname, icon="IMPORT")
        opts = col.column(align=True)
        opts.prop(context.scene, "strinova_do_shading")
        opts.prop(context.scene, "strinova_do_rig")
        opts.prop(context.scene, "strinova_do_paper")
        col.separator()
        col.label(text="Carpeta del personaje:")
        col.prop(context.scene, "strinova_char_dir", text="")
        # weapons are imported apart: many are shared by several skins, and a skin never brings its weapon
        header, body = col.panel("strinova_weapons", default_closed=False)
        header.label(text="Armas", icon="MOD_ARMATURE")
        if body:
            body.operator(weapon.STRINOVA_OT_import_weapon.bl_idname, icon="IMPORT")
        # shading and rig run inside the import; their operators stay registered for it (and F3)
        mesh = common.target_mesh(context)
        omod = mesh.modifiers.get("ST Outline") if mesh else None
        arm = rig.target_rig(context)
        if omod and omod.node_group or arm:
            # per-character settings under its name; collapsible, open/closed state remembered by Blender
            header, body = col.panel("strinova_physics", default_closed=False)
            header.label(text=(arm or mesh).name, icon="ARMATURE_DATA" if arm else "MESH_DATA")
            if body is None:
                return
            if omod and omod.node_group:
                body.prop(shading.mod_input(omod, "Grosor"), "value", text="Grosor contorno")
            if arm and paper.PAPER_PROP in arm:  # animatable: keyframe it to swap in one frame
                body.prop(arm, f'["{paper.PAPER_PROP}"]', text="Version de papel", icon="FILE_IMAGE")
            if arm:
                for k in sorted(k for k in arm.keys() if k.startswith(accessory.SHOW)):  # one per accessory
                    label = k[len(accessory.SHOW):].removeprefix(accessory.PREFIX)
                    body.prop(arm, f'["{k}"]', text=f"Mostrar {label}", icon="HIDE_OFF")
                # greyed out until a piece is selected in Edit Mode
                body.operator(accessory.STRINOVA_OT_accessory.bl_idname, icon="BONE_DATA")
        if arm and rig.PHYSICS_PROP in arm:
            body.separator()
            body.prop(arm, f'["{rig.PHYSICS_PROP}"]', text="Fisica")  # checkbox
            sliders = body.column()
            sliders.active = bool(arm[rig.PHYSICS_PROP])  # greyed out while physics is off
            for prop, _, label in rig.INERTIA_PROPS.values():
                if prop in arm:
                    sliders.prop(arm, f'["{prop}"]', text=label, slider=True)
        if not common.target_mesh(context):
            col.label(text="Selecciona la malla o su armature", icon="INFO")


classes = importer.classes + weapon.classes + shading.classes + rig.classes + accessory.classes + (STRINOVA_PT_panel,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.strinova_do_shading = bpy.props.BoolProperty(
        name="Aplicar Toon Shading", default=True, description="Materiales toon, iluminacion y contorno al importar")
    bpy.types.Scene.strinova_do_rig = bpy.props.BoolProperty(
        name="Generar rig", default=True, description="Rig con Gacha Setup, cara, mirada y fisica al importar")
    bpy.types.Scene.strinova_do_paper = bpy.props.BoolProperty(
        name="Incluir version de papel", default=False,
        description="Importa tambien la version de papel (Mesh2D) de la skin, unida al rig del 3D con su interruptor")
    bpy.types.Scene.strinova_char_dir = bpy.props.StringProperty(
        name="Carpeta del personaje",
        subtype="DIR_PATH",
        default=r"D:\Programas\Fmodel\Output\Exports\PM\Content\PaperMan\SkinAssets\Characters\Kanami",
    )


def unregister():
    del bpy.types.Scene.strinova_char_dir
    del bpy.types.Scene.strinova_do_shading
    del bpy.types.Scene.strinova_do_rig
    del bpy.types.Scene.strinova_do_paper
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
