"""Fast viewport: a switch for animating. The 3D views show the flat textures (Solid mode), without effects nor colour wheels,
and the outline and the light vectors stop being computed, in the viewport only. Nothing is deleted: materials, colours, wheels and their
keyframes stay as they are, renders don't change, and switching it off puts every view and modifier back.
"""
import bpy

MODIFIERS = ("ST Outline", "ST Light Vectors")
SAVED = "st_fast"  # on an object: the modifiers it turned off; on a screen: its views' shading
HIDDEN = "hide_viewport"
WHEELS = ("ST Wheel ", "ST Bar ", "ST Label ")  # useless without colours
EMPTY = "ST Empty"  # 1 px, transparent: Solid mode draws nothing of a material showing it
VIEW = ("type", "color_type", "light")  # in this order: color_type and light are those of the Solid mode


def views(screen):
    return [a.spaces.active.shading for a in screen.areas if a.type == "VIEW_3D"]


def flat_look(mat):
    """What Solid mode shows of a material: its colour texture, or nothing if it is an effect or a glass."""
    nt = mat.node_tree
    if not nt or mat.name.endswith(" Outline"):
        return
    group = next((n for n in nt.nodes if n.type == "GROUP" and "Base Color" in n.inputs and n.inputs["Base Color"].is_linked), None)
    src = group and group.inputs["Base Color"].links[0].from_node
    if src and src.type == "TEX_IMAGE":
        nt.nodes.active = src
    elif mat.get("st_effect") or not any(n.type == "TEX_IMAGE" for n in nt.nodes):
        n = nt.nodes.get(EMPTY)
        if not n:
            n = nt.nodes.new("ShaderNodeTexImage")
            n.name = EMPTY
            n.image = bpy.data.images.get(EMPTY) or bpy.data.images.new(EMPTY, 1, 1, alpha=True)
            n.image.generated_color = (0.0, 0.0, 0.0, 0.0)
        nt.nodes.active = n


def apply(scene):
    """Turn the fast mode on for what isn't yet (also the characters imported while it is on)."""
    for ob in scene.objects:
        off = [m for m in ob.modifiers if m.name in MODIFIERS and m.show_viewport] if ob.type == "MESH" else []
        if ob.name.startswith(WHEELS) and not ob.hide_viewport:
            ob[SAVED], ob.hide_viewport = [HIDDEN], True
        if any(m.name in MODIFIERS for m in ob.modifiers):
            for slot in ob.material_slots:
                if slot.material:
                    flat_look(slot.material)
        if off:
            ob[SAVED] = list(ob.get(SAVED, [])) + [m.name for m in off]
            for m in off:
                m.show_viewport = False
    for screen in bpy.data.screens:
        if SAVED in screen:
            continue
        screen[SAVED] = ",".join("|".join(getattr(s, k) for k in VIEW) for s in views(screen))
        for s in views(screen):
            s.type = "SOLID"
            s.color_type, s.light = "TEXTURE", "FLAT"


def restore(scene):
    for ob in scene.objects:
        for name in ob.get(SAVED, []):
            if name == HIDDEN:
                ob.hide_viewport = False
            elif name in ob.modifiers:
                ob.modifiers[name].show_viewport = True
        if SAVED in ob:
            del ob[SAVED]
    for mat in bpy.data.materials:
        n = mat.node_tree and mat.node_tree.nodes.get(EMPTY)
        if n:
            mat.node_tree.nodes.remove(n)
    for screen in bpy.data.screens:
        if SAVED not in screen:
            continue
        for s, saved in zip(views(screen), screen[SAVED].split(",")):
            kind, color, light = saved.split("|")
            s.type = "SOLID"
            s.color_type, s.light = color, light
            s.type = kind
        del screen[SAVED]


def update(scene, context):
    (apply if scene.strinova_fast_viewport else restore)(scene)
