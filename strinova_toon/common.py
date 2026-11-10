"""Helpers shared by the importer, rig and shading modules."""


def target_mesh(context):
    """The character mesh: the active mesh, or the skinned mesh of the active armature."""
    ob = context.active_object
    if ob and ob.type == "ARMATURE":  # allow selecting the skeleton too
        ob = next((c for c in ob.children if c.type == "MESH" and c.find_armature() == ob), None)
    return ob if ob and ob.type == "MESH" else None
