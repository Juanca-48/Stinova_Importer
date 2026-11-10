bl_info = {
    "name": "Strinova Toon Setup",
    "author": "juanc",
    "version": (0, 2, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar (N) > Strinova",
    "description": "Importa personajes de Strinova (FModel) con toon shading, rig y fisica por constraints",
    "category": "Import-Export",
}

# Strinova (PaperMan) character setup, split by concern so a change in one area cannot break another:
#   importer.py  import .uemodel/.fbx and find the FModel folder
#   rig.py       Rigify rig via Gacha Setup's NTE rigger, rig fixes, hair/clothes/chest physics
#   shading.py   toon materials, lighting panel and sun, outline
#   common.py    helpers shared by all three
if "bpy" in locals():  # add-on reload: refresh the submodules too
    import importlib
    for _m in (common, shading, rig, importer):
        importlib.reload(_m)
else:
    from . import common, shading, rig, importer
import bpy


class STRINOVA_PT_panel(bpy.types.Panel):
    bl_label = "Strinova Toon"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Strinova"

    def draw(self, context):
        col = self.layout.column()
        col.operator(importer.STRINOVA_OT_import.bl_idname, icon="IMPORT")
        col.separator()
        col.label(text="Carpeta del personaje (FModel):")
        col.prop(context.scene, "strinova_char_dir", text="")
        col.operator(shading.STRINOVA_OT_setup.bl_idname, icon="SHADING_RENDERED")
        mesh = common.target_mesh(context)
        omod = mesh.modifiers.get("ST Outline") if mesh else None
        if omod and omod.node_group:
            col.prop(shading.outline_input(omod, "Grosor"), "value", text="Grosor contorno")
        col.operator(rig.STRINOVA_OT_rig.bl_idname, icon="ARMATURE_DATA")
        col.operator(rig.STRINOVA_OT_inertia.bl_idname, icon="FORCE_WIND")
        arm = rig.target_rig(context)
        if arm:
            for prop, _, label in rig.INERTIA_PROPS.values():
                if prop in arm:
                    col.prop(arm, f'["{prop}"]', text=label, slider=True)
        if not common.target_mesh(context):
            col.label(text="Selecciona la malla o su armature", icon="INFO")


classes = importer.classes + shading.classes + rig.classes + (STRINOVA_PT_panel,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.strinova_char_dir = bpy.props.StringProperty(
        name="Carpeta del personaje",
        subtype="DIR_PATH",
        default=r"D:\Programas\Fmodel\Output\Exports\PM\Content\PaperMan\SkinAssets\Characters\Kanami",
    )


def unregister():
    del bpy.types.Scene.strinova_char_dir
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
