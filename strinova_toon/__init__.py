bl_info = {
    "name": "Strinova Toon Setup",
    "author": "juanc",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar (N) > Strinova",
    "description": "Importa personajes de Strinova (FModel) con toon shading, rig y fisica por constraints",
    "category": "Import-Export",
}

# Strinova (PaperMan) character setup: import (.uemodel/.fbx), toon shading from FModel's
# material JSONs, Rigify rig via Gacha Setup's NTE rigger, and constraint-based inertia.
# The shader reuses Gacha Setup's idea of light/head vectors stored as mesh attributes
# (lightDir, headForward, headUp).
# shortcut: shadow colour is a flat tint, not the game's RampID atlas; swap in ramps once exported.
# shortcut: Mask1/Mask2 are not used yet; their channel meaning is still unverified.
import bpy, os, re, json, mathutils
from bpy_extras.io_utils import ImportHelper

SHADOW_TINT = (0.80, 0.70, 0.82, 1.0)


# ---------- file lookup ----------
def index_files(root, ext):
    idx = {}
    for d, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(ext):
                idx.setdefault(os.path.splitext(f)[0], []).append(os.path.join(d, f))
    return idx


def pick(idx, name, skin):
    paths = idx.get(name) or []
    for p in paths:  # prefer the skin folder the asset belongs to
        if f"\\{skin}\\" in p:
            return p
    return paths[0] if paths else None


def skin_of(name, fallback):
    m = re.search(r"_(S\d{3})", name)
    return m.group(1) if m else fallback


# ---------- node helpers ----------
def sock(ng, name, io, typ, default=None):
    s = ng.interface.new_socket(name, in_out=io, socket_type=typ)
    if default is not None:
        s.default_value = default
    return s


def node(nt, typ, x, y, **props):
    n = nt.nodes.new(typ)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def attr(nt, name, x, y):
    a = node(nt, "ShaderNodeAttribute", x, y, attribute_type="GEOMETRY", attribute_name=name)
    nrm = node(nt, "ShaderNodeVectorMath", x + 180, y, operation="NORMALIZE")
    nt.links.new(a.outputs["Vector"], nrm.inputs[0])
    return nrm.outputs[0]


def vmath(nt, op, a, b, x, y):
    n = node(nt, "ShaderNodeVectorMath", x, y, operation=op)
    nt.links.new(a, n.inputs[0])
    if b is not None:
        nt.links.new(b, n.inputs[1])
    return n


def math(nt, op, a, b, x, y):
    n = node(nt, "ShaderNodeMath", x, y, operation=op)
    for i, v in enumerate((a, b)):
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        elif v is not None:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def mix_rgb(nt, blend, fac, a, b, x, y):
    n = node(nt, "ShaderNodeMix", x, y, data_type="RGBA", blend_type=blend, clamp_result=True)
    for i, v in ((0, fac), (6, a), (7, b)):
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[2]


def soft_step(nt, value, center, softness, x, y):
    lo = math(nt, "SUBTRACT", center, softness, x, y + 80)
    hi = math(nt, "ADD", center, softness, x, y - 80)
    mr = node(nt, "ShaderNodeMapRange", x + 180, y, clamp=True)
    nt.links.new(value, mr.inputs["Value"])
    nt.links.new(lo, mr.inputs["From Min"])
    nt.links.new(hi, mr.inputs["From Max"])
    return mr.outputs["Result"]


def shader_out(nt, color, alpha, out_node, x, y):
    em = node(nt, "ShaderNodeEmission", x, y)
    nt.links.new(color, em.inputs["Color"])
    tr = node(nt, "ShaderNodeBsdfTransparent", x, y - 140)
    mx = node(nt, "ShaderNodeMixShader", x + 200, y)
    nt.links.new(alpha, mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out_node.inputs["Shader"])


# ---------- node groups ----------
def build_toon_group():
    ng = bpy.data.node_groups.get("ST Toon")
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("ST Toon", "ShaderNodeTree")
    sock(ng, "Shader", "OUTPUT", "NodeSocketShader")
    sock(ng, "MatCap UV", "OUTPUT", "NodeSocketVector")
    sock(ng, "Base Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    sock(ng, "Alpha", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Normal", "INPUT", "NodeSocketVector").hide_value = True  # always linked by setup_material
    sock(ng, "Shadow Tint", "INPUT", "NodeSocketColor", SHADOW_TINT)
    sock(ng, "Middle Value", "INPUT", "NodeSocketFloat", 0.15)
    sock(ng, "Softness", "INPUT", "NodeSocketFloat", 0.03)
    sock(ng, "MatCap", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    sock(ng, "MatCap Pow", "INPUT", "NodeSocketFloat", 0.0)
    sock(ng, "Emission", "INPUT", "NodeSocketColor", (0, 0, 0, 1))
    nt = ng
    gi = node(nt, "NodeGroupInput", -900, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    L = attr(nt, "lightDir", -700, 300)
    N = vmath(nt, "NORMALIZE", gi.outputs["Normal"], None, -700, 100).outputs[0]
    ndl = vmath(nt, "DOT_PRODUCT", N, L, -400, 200).outputs["Value"]
    lit = soft_step(nt, ndl, gi.outputs["Middle Value"], gi.outputs["Softness"], -200, 200)
    shadow = mix_rgb(nt, "MULTIPLY", 1.0, gi.outputs["Base Color"], gi.outputs["Shadow Tint"], 100, 0)
    col = mix_rgb(nt, "MIX", lit, shadow, gi.outputs["Base Color"], 300, 100)
    col = mix_rgb(nt, "ADD", gi.outputs["MatCap Pow"], col, gi.outputs["MatCap"], 450, 100)
    col = mix_rgb(nt, "ADD", 1.0, col, gi.outputs["Emission"], 600, 100)
    shader_out(nt, col, gi.outputs["Alpha"], go, 650, -150)
    # matcap UV = view-space normal * 0.5 + 0.5
    vt = node(nt, "ShaderNodeVectorTransform", -400, -250, vector_type="NORMAL", convert_from="WORLD", convert_to="CAMERA")
    nt.links.new(N, vt.inputs[0])
    ma = node(nt, "ShaderNodeVectorMath", -200, -250, operation="MULTIPLY_ADD")
    nt.links.new(vt.outputs[0], ma.inputs[0])
    ma.inputs[1].default_value = (0.5, 0.5, 0.5)
    ma.inputs[2].default_value = (0.5, 0.5, 0.5)
    nt.links.new(ma.outputs[0], go.inputs["MatCap UV"])
    return ng


def build_face_group():
    ng = bpy.data.node_groups.get("ST Face")
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("ST Face", "ShaderNodeTree")
    sock(ng, "Shader", "OUTPUT", "NodeSocketShader")
    sock(ng, "SDF UV", "OUTPUT", "NodeSocketVector")
    sock(ng, "Base Color", "INPUT", "NodeSocketColor", (1, 1, 1, 1))
    sock(ng, "Alpha", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "SDF", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Shadow Tint", "INPUT", "NodeSocketColor", SHADOW_TINT)
    sock(ng, "Softness", "INPUT", "NodeSocketFloat", 0.01)
    sock(ng, "Flip Side", "INPUT", "NodeSocketFloat", 0.0)  # set 1 if shadow lands on the wrong side
    nt = ng
    gi = node(nt, "NodeGroupInput", -1300, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    L = attr(nt, "lightDir", -1100, 400)
    F = attr(nt, "headForward", -1100, 250)
    U = attr(nt, "headUp", -1100, 100)
    # light projected on the head's horizontal plane
    lu = vmath(nt, "DOT_PRODUCT", L, U, -800, 400).outputs["Value"]
    su = node(nt, "ShaderNodeVectorMath", -650, 400, operation="SCALE")
    nt.links.new(U, su.inputs[0])
    nt.links.new(lu, su.inputs["Scale"])
    lp = vmath(nt, "SUBTRACT", L, su.outputs[0], -500, 400).outputs[0]
    lp = vmath(nt, "NORMALIZE", lp, None, -350, 400).outputs[0]
    f = vmath(nt, "DOT_PRODUCT", F, lp, -200, 400).outputs["Value"]
    right = vmath(nt, "CROSS_PRODUCT", F, U, -500, 200).outputs[0]
    r = vmath(nt, "DOT_PRODUCT", right, lp, -200, 200).outputs["Value"]
    # mirror the SDF horizontally depending on which side the light is on
    side = math(nt, "GREATER_THAN", r, 0.0, 0, 200)
    side = math(nt, "ABSOLUTE", math(nt, "SUBTRACT", side, gi.outputs["Flip Side"], 150, 250), None, 300, 250)
    uv = node(nt, "ShaderNodeUVMap", -500, -100)
    sep = node(nt, "ShaderNodeSeparateXYZ", -300, -100)
    nt.links.new(uv.outputs[0], sep.inputs[0])
    u = sep.outputs["X"]
    one_minus_2u = math(nt, "MULTIPLY_ADD", u, -2.0, 0, -100)
    nt.nodes[-1].inputs[2].default_value = 1.0
    u2 = math(nt, "MULTIPLY_ADD", side, one_minus_2u, 450, -50)
    nt.links.new(u, nt.nodes[-1].inputs[2])
    comb = node(nt, "ShaderNodeCombineXYZ", 650, -100)
    nt.links.new(u2, comb.inputs["X"])
    nt.links.new(sep.outputs["Y"], comb.inputs["Y"])
    nt.links.new(comb.outputs[0], go.inputs["SDF UV"])
    # lit when SDF exceeds threshold (0 = light in front, 1 = light behind)
    thr = math(nt, "MULTIPLY_ADD", f, -0.5, 0, 450)
    nt.nodes[-1].inputs[2].default_value = 0.5
    lit = soft_step(nt, gi.outputs["SDF"], thr, gi.outputs["Softness"], 200, 450)
    shadow = mix_rgb(nt, "MULTIPLY", 1.0, gi.outputs["Base Color"], gi.outputs["Shadow Tint"], 400, 150)
    col = mix_rgb(nt, "MIX", lit, shadow, gi.outputs["Base Color"], 550, 300)
    shader_out(nt, col, gi.outputs["Alpha"], go, 650, -300)
    return ng


def build_vectors_gn(sun, emp):
    ng = bpy.data.node_groups.get("ST Light Vectors")
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("ST Light Vectors", "GeometryNodeTree")
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nt = ng
    gi = node(nt, "NodeGroupInput", -800, 0)
    go = node(nt, "NodeGroupOutput", 800, 0)

    def info(ob, y):  # objects set on the node itself; modifier object props failed to assign in 5.2
        n = node(nt, "GeometryNodeObjectInfo", -550, y, transform_space="ORIGINAL")
        n.inputs["Object"].default_value = ob
        return n

    li, ho, hf, hu = info(sun, 300), info(emp["Origin"], 0), info(emp["Forward"], -250), info(emp["Up"], -500)
    rot = node(nt, "FunctionNodeRotateVector", -300, 300)
    rot.inputs["Vector"].default_value = (0, 0, 1)  # sun shines along its -Z, so +Z points toward the light
    nt.links.new(li.outputs["Rotation"], rot.inputs["Rotation"])
    fwd = vmath(nt, "SUBTRACT", hf.outputs["Location"], ho.outputs["Location"], -300, -100)
    up = vmath(nt, "SUBTRACT", hu.outputs["Location"], ho.outputs["Location"], -300, -350)
    geo = gi.outputs["Geometry"]
    for i, (name, val) in enumerate((("lightDir", rot.outputs[0]), ("headForward", fwd.outputs[0]), ("headUp", up.outputs[0]))):
        st = node(nt, "GeometryNodeStoreNamedAttribute", 0 + i * 220, 0, data_type="FLOAT_VECTOR", domain="POINT")
        st.inputs["Name"].default_value = name
        nt.links.new(geo, st.inputs["Geometry"])
        nt.links.new(val, st.inputs["Value"])
        geo = st.outputs["Geometry"]
    nt.links.new(geo, go.inputs["Geometry"])
    return ng


# ---------- scene rig: sun + head empties ----------
def ensure_rig(arm):
    # raw FModel skeleton, or the Rigify rig made by "Rig + Fisica"
    head_bone = next((b for b in ("Bip001-Head", "DEF-spine.006") if b in arm.pose.bones), "Bip001-Head")
    col = bpy.context.scene.collection
    sun = bpy.data.objects.get("ST_Light")
    if not sun:
        sun = bpy.data.objects.new("ST_Light", bpy.data.lights.new("ST_Light", "SUN"))
        col.objects.link(sun)
        sun.rotation_euler = (0.9, 0.0, -0.5)  # front, above, slightly to the side
    head = arm.matrix_world @ arm.pose.bones[head_bone].head
    empties = {}
    for name, off in (("Origin", (0, 0, 0)), ("Forward", (0, -0.1, 0)), ("Up", (0, 0, 0.1))):  # model faces -Y
        e = bpy.data.objects.get(f"ST_Head{name}") or bpy.data.objects.new(f"ST_Head{name}", None)
        if e.name not in col.objects:
            col.objects.link(e)
        e.empty_display_size = 0.02
        e.parent, e.parent_type, e.parent_bone = arm, "BONE", head_bone
        bpy.context.view_layer.update()
        mw = e.matrix_world.copy()
        mw.translation = head + mathutils.Vector(off)
        e.matrix_world = mw
        empties[name] = e
    return sun, empties


# ---------- materials ----------
def load_img(path, colorspace):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def tex(nt, path, colorspace, x, y, vector=None):
    n = node(nt, "ShaderNodeTexImage", x, y, image=load_img(path, colorspace))
    if vector is not None:
        nt.links.new(vector, n.inputs["Vector"])
    return n


def setup_material(mat, data, tex_idx, mesh_skin, face_group, toon_group, report):
    skin = skin_of(mat.name, mesh_skin)
    t = {k: v["ObjectName"].split("'")[1] for k, v in data.get("Textures", {}).items() if v}  # FModel writes null for unresolved textures
    sca, cols, sw = data.get("Scalars", {}), data.get("Colors", {}), data.get("Switches", {})
    props = data.get("Properties", {}).get("BasePropertyOverrides", {})
    base_p = pick(tex_idx, t.get("BaseMap", ""), skin)
    if not base_p:
        report[mat.name] = "sin BaseMap, se deja igual"
        return
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    base = tex(nt, base_p, "sRGB", -600, 200)
    is_face = "FaceShadowMask" in t
    g = node(nt, "ShaderNodeGroup", 200, 0, node_tree=face_group if is_face else toon_group)
    nt.links.new(base.outputs["Color"], g.inputs["Base Color"])
    nt.links.new(base.outputs["Alpha"], g.inputs["Alpha"])
    nt.links.new(g.outputs["Shader"], out.inputs["Surface"])
    # second instance only provides the SDF/MatCap UV, so the texture -> group link is not a cycle
    g_uv = node(nt, "ShaderNodeGroup", -500, -350, node_tree=g.node_tree, label="UV only")
    used = [os.path.basename(base_p)]
    if is_face:
        sdf_p = pick(tex_idx, t["FaceShadowMask"], skin)
        if sdf_p:
            sdf = tex(nt, sdf_p, "Non-Color", -200, -250, g_uv.outputs["SDF UV"])
            nt.links.new(sdf.outputs["Color"], g.inputs["SDF"])
            used.append(os.path.basename(sdf_p))
    else:
        mv = sca.get("MiddleValue", 0.15)
        g.inputs["Middle Value"].default_value = mv if mv > -1 else 0.15
        nrm_p = pick(tex_idx, t.get("NormalMap", ""), skin) if sw.get("NeedNormalMap") else None
        if nrm_p:
            n_img = tex(nt, nrm_p, "Non-Color", -800, -150)
            # UE normal maps are DirectX style: flip green for Blender
            sep = node(nt, "ShaderNodeSeparateColor", -550, -150)
            inv = node(nt, "ShaderNodeMath", -380, -150, operation="SUBTRACT")
            inv.inputs[0].default_value = 1.0
            comb = node(nt, "ShaderNodeCombineColor", -220, -150)
            nm = node(nt, "ShaderNodeNormalMap", -60, -150, uv_map="UV0")
            nt.links.new(n_img.outputs["Color"], sep.inputs[0])
            nt.links.new(sep.outputs[0], comb.inputs[0])
            nt.links.new(sep.outputs[1], inv.inputs[1])
            nt.links.new(inv.outputs[0], comb.inputs[1])
            nt.links.new(sep.outputs[2], comb.inputs[2])
            nt.links.new(comb.outputs[0], nm.inputs["Color"])
            nt.links.new(nm.outputs[0], g.inputs["Normal"])
            nt.links.new(nm.outputs[0], g_uv.inputs["Normal"])
            used.append(os.path.basename(nrm_p))
        else:
            geo = node(nt, "ShaderNodeNewGeometry", -60, -150)
            nt.links.new(geo.outputs["Normal"], g.inputs["Normal"])
            nt.links.new(geo.outputs["Normal"], g_uv.inputs["Normal"])
        mc_p = pick(tex_idx, t.get("MatCapTexture", ""), skin) if sw.get("NeedMatCap") else None
        if mc_p:
            mc = tex(nt, mc_p, "sRGB", -200, -450, g_uv.outputs["MatCap UV"])
            nt.links.new(mc.outputs["Color"], g.inputs["MatCap"])
            g.inputs["MatCap Pow"].default_value = sca.get("MatCapPow", 0.0)
            used.append(os.path.basename(mc_p))
        e = cols.get("EmissiveColor")
        if e:
            g.inputs["Emission"].default_value = (e["R"], e["G"], e["B"], 1)
    translucent = props.get("BlendMode") == "BLEND_Translucent"
    mat.surface_render_method = "BLENDED" if translucent else "DITHERED"
    mat.use_backface_culling = not props.get("TwoSided", False)
    report[mat.name] = {"tipo": "face" if is_face else "toon", "texturas": used}


def run(obj, char_dir):
    arm = obj.find_armature()
    mesh_skin = skin_of(obj.name, "")
    tex_idx = index_files(char_dir, ".png")
    json_idx = index_files(char_dir, ".json")
    sun, emp = ensure_rig(arm)
    toon_g, face_g, gn = build_toon_group(), build_face_group(), build_vectors_gn(sun, emp)
    mod = obj.modifiers.get("ST Light Vectors") or obj.modifiers.new("ST Light Vectors", "NODES")
    mod.node_group = gn
    report = {}
    for slot in obj.material_slots:
        mat = slot.material
        base_name = re.sub(r"\.\d{3}$", "", mat.name)  # Blender adds .001 on name clashes (re-imports, FBX)
        jp = pick(json_idx, base_name, skin_of(base_name, mesh_skin))
        if not jp:
            report[mat.name] = "sin JSON, se deja igual"
            continue
        with open(jp, encoding="utf-8") as fh:
            setup_material(mat, json.load(fh), tex_idx, mesh_skin, face_g, toon_g, report)
    return report


# ---------- UI ----------
def target_mesh(context):
    ob = context.active_object
    if ob and ob.type == "ARMATURE":  # allow selecting the skeleton too
        ob = next((c for c in ob.children if c.type == "MESH" and c.find_armature() == ob), None)
    return ob if ob and ob.type == "MESH" else None


# ---------- rig + physics ----------
PHYS_COLLECTIONS = ("Hair", "Clothes")
NOT_PHYSICS = {"SocketADS"}  # gameplay socket Gacha Setup files under Clothes


INERTIA_PROPS = {"Hair": ("st_hair_inertia", 0.5), "Clothes": ("st_cloth_inertia", 0.3)}


def apply_inertia(rig):
    """Constraint 'physics' that reacts live without playback. Each Hair/Clothes chain
    root copies part of the rotation of a hidden helper (STI-*) parented to the rig's
    root, so when the head/torso turns the chain only partly follows and seems to hang.
    Gacha Setup's Damped Track (bone tracks its own child) is not used: on this rig it
    makes dependency cycles, twists chains at rest and hits Rigify MCH bones."""
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="OBJECT")
    colls = rig.data.collections_all
    owner = {b.name: c for c in PHYS_COLLECTIONS if c in colls for b in colls[c].bones if b.name not in NOT_PHYSICS}
    roots = [n for n in owner if not (rig.data.bones[n].parent and rig.data.bones[n].parent.name in owner)]
    for c in PHYS_COLLECTIONS:
        if c in colls:
            colls[c].is_visible = True
    for c, (prop, default) in INERTIA_PROPS.items():
        if prop not in rig:
            rig[prop] = default
        rig.id_properties_ui(prop).update(min=0.0, max=1.0, description=f"Cuanto se resiste {c} a seguir el movimiento")

    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    hidden = colls.get("ST Inertia") or rig.data.collections.new("ST Inertia")
    hidden.is_visible = False
    for n in roots:
        h = eb.get("STI-" + n) or eb.new("STI-" + n)
        src = eb[n]
        h.head, h.tail, h.roll = src.head.copy(), src.tail.copy(), src.roll
        h.parent = eb.get("root")
        h.use_deform = False
        hidden.assign(h)
    bpy.ops.object.mode_set(mode="POSE")
    for n in roots:
        pb = rig.pose.bones[n]
        c = pb.constraints.get("ST Inertia") or pb.constraints.new("COPY_ROTATION")
        c.name, c.target, c.subtarget = "ST Inertia", rig, "STI-" + n
        pb.driver_remove(f'constraints["ST Inertia"].influence')
        drv = c.driver_add("influence").driver
        drv.type = "AVERAGE"
        t = drv.variables.new().targets[0]
        t.id, t.data_path = rig, f'["{INERTIA_PROPS[owner[n]][0]}"]'
    bpy.ops.object.mode_set(mode="OBJECT")
    return len(roots)


def target_rig(context):
    ob = context.active_object
    if ob and ob.type == "MESH":
        ob = ob.find_armature()
    return ob if ob and ob.type == "ARMATURE" and "Hair" in ob.data.collections_all else None


class STRINOVA_OT_inertia(bpy.types.Operator):
    bl_idname = "strinova.inertia"
    bl_label = "Fisica por Constraints"
    bl_description = "Pelo y ropa reaccionan en tiempo real al girar cabeza/torso, sin simulacion"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_rig(context) is not None

    def execute(self, context):
        n = apply_inertia(target_rig(context))
        self.report({"INFO"}, f"{n} cadenas con inercia")
        return {"FINISHED"}


class STRINOVA_OT_rig(bpy.types.Operator):
    bl_idname = "strinova.rig_physics"
    bl_label = "Rig + Fisica"
    bl_description = "Genera el rig Rigify con Gacha Setup (modo NTE) y la fisica por constraints en pelo y ropa"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_mesh(context) is not None

    def execute(self, context):
        prefs = context.preferences.addons
        if "setup_wizard" not in prefs:
            self.report({"ERROR"}, "Activa el add-on Gacha Setup")
            return {"CANCELLED"}
        obj = target_mesh(context)
        arm = obj.find_armature()
        if not arm:
            self.report({"ERROR"}, f"{obj.name} no tiene armature")
            return {"CANCELLED"}
        if "Bip001-Pelvis" not in arm.data.bones:
            self.report({"ERROR"}, f"{arm.name} ya esta riggeado o no es un esqueleto de Strinova")
            return {"CANCELLED"}
        for o in context.view_layer.objects:
            o.select_set(False)
        context.view_layer.objects.active = arm
        arm.select_set(True)
        # NTE shares Strinova's hyphenated Bip001 skeleton, so Gacha Setup's NTE rigger maps it as is
        bpy.ops.hoyoverse.rig_character(game_type="NEVERNESS_TO_EVERNESS")
        rig = obj.find_armature()
        if not rig or "DEF-spine.006" not in rig.pose.bones:
            self.report({"ERROR"}, "Gacha Setup no genero el rig (revisa la consola)")
            return {"CANCELLED"}
        n = apply_inertia(rig)
        self.report({"INFO"}, f"Rig listo: {rig.name}, {n} cadenas con fisica por constraints")
        return {"FINISHED"}


class STRINOVA_OT_setup(bpy.types.Operator):
    bl_idname = "strinova.setup_toon"
    bl_label = "Aplicar Toon Shading"
    bl_description = "Crea los node groups, el rig de luz/cabeza y reconstruye los materiales del personaje"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and target_mesh(context) is not None

    def execute(self, context):
        obj = target_mesh(context)
        char_dir = bpy.path.abspath(context.scene.strinova_char_dir)
        if not os.path.isdir(char_dir):
            self.report({"ERROR"}, f"Carpeta no encontrada: {char_dir}")
            return {"CANCELLED"}
        if not obj.find_armature():
            self.report({"ERROR"}, f"{obj.name} no tiene armature")
            return {"CANCELLED"}
        try:
            report = run(obj, char_dir)
        except KeyError as e:  # missing head bone
            self.report({"ERROR"}, f"No se encontro el hueso {e}")
            return {"CANCELLED"}
        for k, v in report.items():
            print(f"[Strinova] {k}: {v}")
        done = sum(isinstance(v, dict) for v in report.values())
        self.report({"INFO"}, f"{done}/{len(report)} materiales configurados (detalle en la consola)")
        return {"FINISHED"}


def char_dir_from(path):
    # FModel layout: .../Characters/<Name>/<Skin>/Mesh3D/SK_*.uemodel
    parts = os.path.normpath(path).split(os.sep)
    if "Characters" in parts and parts.index("Characters") + 1 < len(parts) - 1:
        return os.sep.join(parts[: parts.index("Characters") + 2])
    return None  # e.g. an FBX saved elsewhere: keep the folder already set in the panel


class STRINOVA_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "strinova.import_character"
    bl_label = "Importar personaje"
    bl_description = "Importa un .uemodel (UEFormat) o .fbx del personaje y opcionalmente aplica shading y rig"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(default="*.uemodel;*.fbx", options={"HIDDEN"})
    do_shading: bpy.props.BoolProperty(name="Aplicar Toon Shading", default=True)
    do_rig: bpy.props.BoolProperty(name="Rig + Fisica", default=True)

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
        before = set(bpy.data.objects)
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
        char_dir = char_dir_from(self.filepath)
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
        steps = [("shading", self.do_shading, bpy.ops.strinova.setup_toon), ("rig", self.do_rig, bpy.ops.strinova.rig_physics)]
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
        msg = f"{mesh.name}: " + ", ".join(done) + (f" | fallo: {', '.join(failed)} (ver consola)" if failed else "")
        self.report({"WARNING" if failed else "INFO"}, msg)
        return {"FINISHED"}


class STRINOVA_PT_panel(bpy.types.Panel):
    bl_label = "Strinova Toon"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Strinova"

    def draw(self, context):
        col = self.layout.column()
        col.operator(STRINOVA_OT_import.bl_idname, icon="IMPORT")
        col.separator()
        col.label(text="Carpeta del personaje (FModel):")
        col.prop(context.scene, "strinova_char_dir", text="")
        col.operator(STRINOVA_OT_setup.bl_idname, icon="SHADING_RENDERED")
        col.operator(STRINOVA_OT_rig.bl_idname, icon="ARMATURE_DATA")
        col.operator(STRINOVA_OT_inertia.bl_idname, icon="FORCE_WIND")
        rig = target_rig(context)
        if rig and "st_hair_inertia" in rig:
            col.prop(rig, '["st_hair_inertia"]', text="Inercia pelo", slider=True)
            col.prop(rig, '["st_cloth_inertia"]', text="Inercia ropa", slider=True)
        if not target_mesh(context):
            col.label(text="Selecciona la malla o su armature", icon="INFO")


classes = (STRINOVA_OT_import, STRINOVA_OT_setup, STRINOVA_OT_rig, STRINOVA_OT_inertia, STRINOVA_PT_panel)


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
