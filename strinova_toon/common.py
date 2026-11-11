"""Helpers shared by several modules."""


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
