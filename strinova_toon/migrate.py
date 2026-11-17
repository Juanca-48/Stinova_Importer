# SPDX-License-Identifier: GPL-3.0-or-later
"""Scenes made before 1.2 have Spanish names for what the add-on creates (bones, bone collections,
constraints, node group inputs...). They are renamed once to the English names the code uses, when a
file is opened and when the add-on is enabled, so the rest of the add-on only knows one name for each.
Bone renames go through Blender, which also fixes constraints, drivers, keyframes and vertex groups."""
import re
import bpy
from bpy.app.handlers import persistent

# face section and sub-section words (bone collections "Cara: X", frame and label bones)
WORDS = {"Cabeza y otros": "Head & Other", "Boca interior": "Inner Mouth", "Ojos": "Eyes", "Pupilas": "Pupils",
         "Cejas": "Brows", "Boca": "Mouth", "Labios": "Lips", "Fonemas": "Phonemes", "Ambos": "Both",
         "Derecha": "Right", "Izquierda": "Left", "Huesos": "Bones", "Mirada": "Gaze"}
_WORD = re.compile(r"\b(%s)\b" % "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)))

BONES = (  # (pattern, replacement), on every armature; the trailing group keeps Blender's .001
    (r"^ST Sol(\.\d+)?$", r"ST Sun\1"),
    (r"^ST Luz( centro| valor)?(\.\d+)?$", r"ST Light\1\2"),
    (r"^ST Ambiente( centro| valor)?(\.\d+)?$", r"ST Ambient\1\2"),
    (r"^(GUIDE-ST )?CTRL-ST Parpadeo(\.\d+)?$", r"\1CTRL-ST Blink\2"),
    (r"^(MCH-)?Mirada(\.[LR])?$", r"\1Gaze\2"),
    (r"^ACC-Mascara(\.\d+)?$", r"ACC-Mask\1"),
)
WEAPON_BONES = (  # only on weapon rigs: "Mira" is too short to rename anywhere else
    (r"^Agarre guia(\.\d+)?$", r"ST Grip Guide\1"),
    (r"^Agarre(\.\d+)?$", r"ST Grip\1"),
    (r"^Mira(?=$| |\.\d)", "Sight Part"),
    (r"^Colgante(?=$| |\.\d)", "Pendant Part"),
    (r"^Cargador(?=$| |\.\d)", "Magazine Part"),
)
SUFFIX = ((r" centro(?=$|\.)", " Center"), (r" valor(?=$|\.)", " Value"))
BONE_COLLECTIONS = {"Iluminacion": "Lighting", "Accesorios": "Accessories", "Arma": "Weapon"}
CONSTRAINTS = {"ST Sol": "ST Sun", "ST Cabeza": "ST Head", "ST Mirada": "ST Gaze", "ST Mano derecha": "ST Right Hand",
               "ST Mano izquierda (agarre)": "ST Left Hand (Grip)"}
GROUPS = {"ST Ocultar grupo": "ST Hide Group", "ST Ocultar": "ST Hide"}
SOCKETS = {"Grosor": "Width", "Primer slot de contorno": "First Outline Slot", "Brillo metal": "Metal Shine",
           "Emision": "Emissive", "Sol": "Sun", "Cabeza": "Head", "Cabeza frente": "Head Forward",
           "Cabeza arriba": "Head Up", "Grupo": "Group"}
FRAMES = {
    "Color de luz y ambiente (panel de iluminacion)": "Light and ambient colour (lighting panel)",
    "Mezcla luz / sombra": "Light / shadow mix", "Entradas": "Inputs", "Entrada": "Input",
    "Luz: N.L con la direccion del sol (lado iluminado)": "Light: N.L with the sun direction (lit side)",
    "UV del MatCap (normal en espacio de camara)": "MatCap UV (camera-space normal)",
    "MatCap y emision": "MatCap and emission", "Salida (emision + transparencia)": "Output (emission + transparency)",
    "Vectores: luz y orientacion de la cabeza": "Vectors: light and head orientation",
    "Luz proyectada en el plano de la cabeza (delante / lado)": "Light projected on the head plane (front / side)",
    "UV del SDF: espejo segun el lado de la luz": "SDF UV: mirrored by the light side",
    "Sombra de la cara: umbral del SDF (0 = luz delante, 1 = detras)": "Face shadow: SDF threshold (0 = light in front, 1 = behind)",
    "Objetos: sol y empties de la cabeza (los pone el modificador)": "Objects: sun and head empties (set by the modifier)",
    "Vectores: direccion de la luz, frente y arriba de la cabeza": "Vectors: light direction, head forward and up",
    "Guardar como atributos (los lee el shader)": "Store as attributes (read by the shader)",
    "Textura base (color + alpha)": "Base texture (colour + alpha)", "UV calculadas (SDF / MatCap)": "Computed UVs (SDF / MatCap)",
    "Toon shading de la cara (ST Face)": "Toon shading for the face (ST Face)", "Salida": "Output",
    "RMO: R emision, G rugosidad, B metal": "RMO: R emission, G roughness, B metal",
    "Brillo del metal (matcap donde el metal es pulido) y emision": "Metal shine (matcap where the metal is polished) and emission",
    "Salida (emision + recorte de transparencia)": "Output (emission + alpha clip)",
    "UV calculadas (MatCap)": "Computed UVs (MatCap)", "Toon de arma (ST Weapon)": "Weapon toon (ST Weapon)",
    "Normal de la geometria (sin normal map)": "Geometry normal (no normal map)",
    "Normal map (DirectX a Blender: canal verde invertido)": "Normal map (DirectX to Blender: green channel flipped)",
}
PANEL_OBJECTS = re.compile(r"^ST (Rueda|Barra|Texto) (Luz|Ambiente)(\.\d+)?$")
PANEL_WORDS = {"Rueda": "Wheel", "Barra": "Bar", "Texto": "Label", "Luz": "Light", "Ambiente": "Ambient"}
SHOW = "st_show_"
OLD_ACC, NEW_ACC = "ACC-Mascara", "ACC-Mask"


def _sub(name, rules):
    for pat, rep in rules:
        new = re.sub(pat, rep, name)
        if new != name:
            return new
    return name


def _fcurves():
    """Every driver and keyframe curve in the file (Blender 5: keyframes live in action channelbags)."""
    for ob in bpy.data.objects:
        if ob.animation_data:
            yield from ob.animation_data.drivers
    for act in bpy.data.actions:
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves


def _rename_prop(rig, old, new):
    """A rig property whose name holds a bone name (st_show_ACC-Mascara): Blender does not follow it."""
    if old not in rig or new in rig:
        return
    ui = rig.id_properties_ui(old).as_dict()
    rig[new] = rig[old]
    del rig[old]
    rig.id_properties_ui(new).update(**{k: v for k, v in ui.items() if k in ("description", "min", "max", "soft_min", "soft_max", "default")})
    old_path, new_path = f'["{old}"]', f'["{new}"]'
    for fc in _fcurves():
        if old_path in fc.data_path:
            fc.data_path = fc.data_path.replace(old_path, new_path)
        if fc.driver:
            for v in fc.driver.variables:
                for t in v.targets:
                    if t.data_path and old_path in t.data_path:
                        t.data_path = t.data_path.replace(old_path, new_path)


def _armature(arm):
    from . import face
    n = 0
    rules = BONES + (WEAPON_BONES if arm.get("st_weapon_rig") else ())
    for b in list(arm.data.bones):
        new = _sub(_sub(b.name, rules), SUFFIX) if b.name.startswith(("ST Luz", "ST Ambiente")) else _sub(b.name, rules)
        if b.name.startswith(("FRAME-ST ", "LABEL-ST ")):
            new = _WORD.sub(lambda m: WORDS[m.group(1)], b.name)
        if new != b.name and new not in arm.data.bones:
            b.name = new  # Blender fixes constraints, drivers, keyframes and vertex groups
            n += 1
    for c in list(arm.data.collections_all):  # a list: merging removes collections
        new = BONE_COLLECTIONS.get(c.name) or (
            "Face: " + _WORD.sub(lambda m: WORDS[m.group(1)], c.name[6:]) if c.name.startswith("Cara: ") else None)
        if new and new != c.name:
            same = arm.data.collections_all.get(new)
            if same:  # Gacha's rigger already made an (empty) "Lighting": merge into it, like a new import does
                for b in list(c.bones):
                    same.assign(b)
                arm.data.collections.remove(c)
                n += 1
                continue
            c.name = new
            if getattr(c, "rigify_ui_title", None):
                c.rigify_ui_title = _WORD.sub(lambda m: WORDS[m.group(1)], c.rigify_ui_title)
            n += 1
    for pb in arm.pose.bones:
        for c in pb.constraints:
            if c.name in CONSTRAINTS:
                c.name = CONSTRAINTS[c.name]
                n += 1
        # face titles: their outline text is the bone's shape
        if pb.name.startswith("LABEL-ST ") and pb.custom_shape and pb.custom_shape.name.startswith("WGT-ST_face_"):
            text = pb.custom_shape.name[len("WGT-ST_face_"):]
            if _WORD.fullmatch(text):
                pb.custom_shape = face.text_widget(WORDS[text])
                n += 1
    _rename_prop(arm, SHOW + OLD_ACC, SHOW + NEW_ACC)
    return n


def migrate():
    """Rename what the add-on made with older versions; returns how many names changed."""
    n = 0
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE" and ob.library is None:
            n += _armature(ob)
    for ob in bpy.data.objects:
        if ob.library:
            continue
        for c in ob.constraints:
            if c.name in CONSTRAINTS:
                c.name = CONSTRAINTS[c.name]
                n += 1
        m = PANEL_OBJECTS.match(ob.name)
        if m:
            ob.name = f"ST {PANEL_WORDS[m.group(1)]} {PANEL_WORDS[m.group(2)]}{m.group(3) or ''}"
            if ob.type == "FONT" and ob.data.body in PANEL_WORDS:
                ob.data.body = PANEL_WORDS[ob.data.body]
            n += 1
        if ob.type == "MESH":
            vg = ob.vertex_groups.get(f"ST {OLD_ACC}")
            if vg and f"ST {NEW_ACC}" not in ob.vertex_groups:
                vg.name = f"ST {NEW_ACC}"
            for mod in ob.modifiers:
                if mod.name.startswith("ST Ocultar"):
                    mod.name = mod.name.replace("ST Ocultar", "ST Hide", 1).replace(OLD_ACC, NEW_ACC)
                    n += 1
    for ng in bpy.data.node_groups:
        if ng.library or not ng.name.startswith("ST "):
            continue
        base = re.sub(r" \(v\d+\)$", "", ng.name)
        if base in GROUPS:
            ng.name = ng.name.replace(base, GROUPS[base], 1)
            n += 1
        for item in ng.interface.items_tree:
            if getattr(item, "name", None) in SOCKETS and item.item_type == "SOCKET":
                item.name = SOCKETS[item.name]
                n += 1
        for node in ng.nodes:
            if node.type == "FRAME" and node.label in FRAMES:
                node.label = FRAMES[node.label]
    for ob in bpy.data.objects:  # the accessory switch's "Group" input names its vertex group
        for mod in getattr(ob, "modifiers", ()):
            if mod.type == "NODES" and mod.node_group and mod.node_group.name.startswith("ST Hide Group"):
                from .shading import mod_input
                inp = mod_input(mod, "Group")
                if inp.value == f"ST {OLD_ACC}":
                    inp.value = f"ST {NEW_ACC}"
    for coll in bpy.data.collections:  # a weapon's own collection
        if coll.library is None and coll.name.startswith("Arma ") and any(o.get("st_weapon") or o.get("st_weapon_rig") for o in coll.all_objects):
            coll.name = "Weapon " + coll.name[5:]
            n += 1
    if n:
        print(f"[Strinova] {n} old Spanish names renamed to English")
    return n


@persistent
def on_load(_):
    migrate()


def register():
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.timers.register(lambda: migrate() and None, first_interval=0.1)  # the file open while enabling


def unregister():
    for h in [h for h in bpy.app.handlers.load_post if getattr(h, "__module__", "") == __name__]:
        bpy.app.handlers.load_post.remove(h)  # by module: a reloaded add-on has a new on_load
