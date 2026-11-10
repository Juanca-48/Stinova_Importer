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
from math import cos, sin, tau  # imported by name: math() below is a node helper
from bpy_extras.io_utils import ImportHelper

SHADOW_TINT = (0.80, 0.70, 0.82, 1.0)


# ---------- file lookup ----------
def index_files(root, ext):
    idx = {}
    for d, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(ext):
                # case-insensitive: JSONs say T_Aika_body_1_D for the file T_Aika_Body_1_D.png
                idx.setdefault(os.path.splitext(f)[0].lower(), []).append(os.path.join(d, f))
    return idx


def pick(idx, name, skin):
    paths = idx.get(name.lower()) or []
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


def hsv_wheel(nt, a, b, value, x, y):
    """Colour from a point on the lighting panel wheel: angle = hue, radius = saturation."""
    ang = math(nt, "ARCTAN2", b, a, x, y)
    hue = math(nt, "FRACT", math(nt, "DIVIDE", ang, tau, x + 150, y), None, x + 300, y)
    r2 = math(nt, "ADD", math(nt, "MULTIPLY", a, a, x, y - 120), math(nt, "MULTIPLY", b, b, x, y - 200), x + 150, y - 160)
    sat = math(nt, "MINIMUM", math(nt, "SQRT", r2, None, x + 300, y - 160), 1.0, x + 450, y - 160)
    cc = node(nt, "ShaderNodeCombineColor", x + 600, y, mode="HSV")
    nt.links.new(hue, cc.inputs[0])
    nt.links.new(sat, cc.inputs[1])
    nt.links.new(value, cc.inputs[2])
    return cc.outputs[0]


def scene_color(nt, name, x, y):
    # View Layer attribute reads the scene custom property (x, z, value of a panel picker,
    # copied there by drivers), so one panel drives every material
    a = node(nt, "ShaderNodeAttribute", x - 400, y, attribute_type="VIEW_LAYER", attribute_name=name)
    sep = node(nt, "ShaderNodeSeparateXYZ", x - 250, y)
    nt.links.new(a.outputs["Vector"], sep.inputs[0])
    return hsv_wheel(nt, sep.outputs["X"], sep.outputs["Y"], sep.outputs["Z"], x - 100, y)


def toon_mix(nt, lit, base, tint, x, y):
    """Lit side = base * light colour, shadow side = base * shadow tint * ambient colour."""
    light = scene_color(nt, "st_light_pick", x - 200, y + 250)
    ambient = scene_color(nt, "st_ambient_pick", x - 200, y - 250)
    shadow = mix_rgb(nt, "MULTIPLY", 1.0, mix_rgb(nt, "MULTIPLY", 1.0, base, tint, x, y - 100), ambient, x + 150, y - 100)
    return mix_rgb(nt, "MIX", lit, shadow, mix_rgb(nt, "MULTIPLY", 1.0, base, light, x, y + 100), x + 300, y)


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
    col = toon_mix(nt, lit, gi.outputs["Base Color"], gi.outputs["Shadow Tint"], 100, 100)
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
    col = toon_mix(nt, lit, gi.outputs["Base Color"], gi.outputs["Shadow Tint"], 400, 150)
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
        # EmissiveColor is a leftover default in ~700 materials; the game only uses it behind the
        # EnableEmissive static switch (otherwise it whites out e.g. Chiyo S105, Aika S207 face).
        # shortcut: applied unmasked; find the emission mask channel if a material glows too much.
        e = cols.get("EmissiveColor") if sw.get("EnableEmissive") else None
        if e:
            g.inputs["Emission"].default_value = (e["R"], e["G"], e["B"], 1)
    translucent = props.get("BlendMode") == "BLEND_Translucent"
    mat.surface_render_method = "BLENDED" if translucent else "DITHERED"
    mat.use_backface_culling = not props.get("TwoSided", False)
    report[mat.name] = {"tipo": "face" if is_face else "toon", "texturas": used}


# ---------- lighting panel (HSV wheels in the viewport, like Gacha Setup's Genshin panel) ----------
PANEL = "ST Lighting Panel"  # standalone armature until the character gets a rig, then joined into it
PICKERS = (("Luz", "st_light_pick", 0.0), ("Ambiente", "st_ambient_pick", 0.30))  # name, scene prop, x offset (m)
R = 0.08  # wheel radius in metres; drivers divide by it so the shader works with a unit wheel
VALUE_MAX = 1.5  # value slider range (1 = texture colour, >1 overexposes)
SLIDER_DX = 0.14
SUN_DIST = 0.8  # default distance of the sun handle from the head
COLL = "Iluminacion"


def _mesh_obj(name, verts, faces, parent, loc, mat=None, edges=None):
    me = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    me.clear_geometry()
    if edges is None:
        edges = [] if faces else [(i, (i + 1) % len(verts)) for i in range(len(verts))]
    me.from_pydata(verts, edges, faces or [])
    if mat and not me.materials:
        me.materials.append(mat)
    ob = bpy.data.objects.get(name) or bpy.data.objects.new(name, me)
    if parent:
        ob.parent, ob.location = parent, loc
        ob.hide_select = ob.hide_render = True  # viewport-only UI
    return ob


def _circle(r, n=48):
    return [(r * cos(tau * i / n), 0.0, r * sin(tau * i / n)) for i in range(n)]


def _emission_mat(name, build):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    tc = node(nt, "ShaderNodeTexCoord", -900, 0)
    sep = node(nt, "ShaderNodeSeparateXYZ", -700, 0)
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    em = node(nt, "ShaderNodeEmission", 400, 0)
    nt.links.new(build(nt, sep), em.inputs["Color"])
    nt.links.new(em.outputs[0], node(nt, "ShaderNodeOutputMaterial", 600, 0).inputs["Surface"])
    return m


def _wheel_colour(nt, sep):
    one = node(nt, "ShaderNodeValue", -500, -300)
    one.outputs[0].default_value = 1.0
    x = math(nt, "DIVIDE", sep.outputs["X"], R, -600, 100)
    z = math(nt, "DIVIDE", sep.outputs["Z"], R, -600, -100)
    return hsv_wheel(nt, x, z, one.outputs[0], -500, 0)


def _ramp_colour(nt, sep):
    v = math(nt, "DIVIDE", sep.outputs["Z"], VALUE_MAX * R, -500, 0)
    cc = node(nt, "ShaderNodeCombineColor", -300, 0)
    for i in range(3):
        nt.links.new(v, cc.inputs[i])
    return cc.outputs[0]


def _reparent(context, ob, parent, bone=None):
    """Change parent keeping the world transform."""
    mw = ob.matrix_world.copy()
    ob.parent = parent
    ob.parent_type = "BONE" if bone else "OBJECT"
    ob.parent_bone = bone or ""
    context.view_layer.update()
    ob.matrix_world = mw


def _head_bone(arm):
    return next((b for b in ("DEF-spine.006", "Bip001-Head") if b in arm.data.bones), None)


def create_panel(context, near, char_arm):
    """Standalone armature: an HSV wheel + value slider per colour and the sun handle."""
    sc = context.scene
    arm = bpy.data.armatures.new(PANEL)
    arm.display_type = "WIRE"
    pan = bpy.data.objects.new(PANEL, arm)
    sc.collection.objects.link(pan)
    bb = [near.matrix_world @ mathutils.Vector(c) for c in near.bound_box]
    pan.location = (max(v.x for v in bb) + 0.4, 0.0, max(v.z for v in bb) * 0.8)
    pan.show_in_front = True
    hb = _head_bone(char_arm)
    head = char_arm.matrix_world @ char_arm.data.bones[hb].head_local if hb else pan.location
    to_light = mathutils.Euler((0.9, 0.0, -0.5)).to_matrix() @ mathutils.Vector((0, 0, 1))  # front, above, to the side
    sun_at = head + to_light * SUN_DIST - pan.location
    prev = context.view_layer.objects.active
    context.view_layer.objects.active = pan
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    def bone(name, head, parent=None, length=0.03):
        b = eb.new(name)
        b.head, b.tail, b.parent = head, (head[0], head[1] + length, head[2]), parent
        return b

    root = bone("ST Panel", (0, 0, 0))
    for name, _, ox in PICKERS:
        bone(f"ST {name} centro", (ox, 0, 0), root)
        bone(f"ST {name}", (ox, 0, 0), root)
        bone(f"ST {name} valor", (ox + SLIDER_DX, 0, 0), root)
    bone("ST Sol", tuple(sun_at), None, 0.05)
    bpy.ops.object.mode_set(mode="OBJECT")
    context.view_layer.objects.active = prev
    wheel_mat = _emission_mat("ST Wheel", _wheel_colour)
    ramp_mat = _emission_mat("ST Value Ramp", _ramp_colour)
    n = 64
    for name, _, ox in PICKERS:
        disc = _mesh_obj(f"ST Rueda {name}", [(0, 0, 0)] + _circle(R, n), [(0, i + 1, (i + 1) % n + 1) for i in range(n)], pan, (ox, 0.005, 0), wheel_mat)
        h = VALUE_MAX * R
        track = _mesh_obj(f"ST Barra {name}", [(-0.006, 0, 0), (0.006, 0, 0), (0.006, 0, h), (-0.006, 0, h)], [(0, 1, 2, 3)], pan, (ox + SLIDER_DX, 0.005, 0), ramp_mat)
        label = bpy.data.objects.get(f"ST Texto {name}") or bpy.data.objects.new(f"ST Texto {name}", bpy.data.curves.new(f"ST Texto {name}", "FONT"))
        label.data.body, label.data.size, label.data.align_x = name, 0.035, "CENTER"
        label.parent, label.location, label.rotation_euler = pan, (ox + 0.03, 0.005, R + 0.04), (1.5708, 0, 0)
        label.hide_select = label.hide_render = True
        for ob in (disc, track, label):
            if ob.name not in sc.collection.objects:
                sc.collection.objects.link(ob)
    for name, _, _ in PICKERS:
        pan.pose.bones[f"ST {name} valor"].location = (0, 0, R)  # value 1 until a preset is applied
    return pan


def merge_panel(context, pan, rig):
    """Join the panel into the character rig (like Gacha Setup does with Genshin's panel), so
    lights animate in the same action as the character."""
    ui = list(pan.children)
    ui_mw = {c: c.matrix_world.copy() for c in ui}
    locs = {pb.name: pb.location.copy() for pb in pan.pose.bones}
    pan_mw = pan.matrix_world.copy()
    pan.parent = None
    pan.matrix_world = pan_mw
    if not pan.users_collection:
        context.scene.collection.objects.link(pan)
    context.view_layer.update()
    for o in context.view_layer.objects:
        o.select_set(False)
    pan.hide_set(False)
    pan.select_set(True)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for b in ("ST Panel", "ST Sol"):
        eb[b].parent = eb.get("root")
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, loc in locs.items():
        rig.pose.bones[name].location = loc
    context.view_layer.update()
    for c in ui:
        c.parent, c.parent_type, c.parent_bone = rig, "BONE", "ST Panel"
        context.view_layer.update()
        c.matrix_world = ui_mw[c]
    coll = rig.data.collections_all.get(COLL) or rig.data.collections.new(COLL)
    for b in rig.data.bones:
        if b.name.startswith("ST "):
            for c in list(b.collections):
                c.unassign(b)
            coll.assign(b)
    coll.is_visible = True


def bind_lighting(context, arm, char_arm):
    """Pose settings, limits, drivers and sun constraints for the lighting controls in `arm`."""
    sc = context.scene
    ring = _mesh_obj("WGT-ST_picker", _circle(0.012), None, None, None)
    bar = _mesh_obj("WGT-ST_slider", [(-0.02, 0, 0), (0.02, 0, 0)], None, None, None)
    circ = _circle(0.03, 24)
    rays_out = [(0.06 * cos(tau * i / 8), 0, 0.06 * sin(tau * i / 8)) for i in range(8)]
    rays_in = [(0.04 * cos(tau * i / 8), 0, 0.04 * sin(tau * i / 8)) for i in range(8)]
    sun_w = _mesh_obj("WGT-ST_sun", circ + rays_out + rays_in, None, None, None,
                      edges=[(i, (i + 1) % 24) for i in range(24)] + [(24 + i, 32 + i) for i in range(8)])
    pb = arm.pose.bones
    helpers = ("ST Panel",) + tuple(f"ST {n} centro" for n, _, _ in PICKERS)
    for p in pb:
        if p.name.startswith("ST "):
            hidden = p.name in helpers
            p.bone.hide = hidden
            p.hide = hidden  # Blender 5: pose-mode visibility lives on the pose bone
            p.use_custom_shape_bone_size = False  # widgets in metres, not scaled by the 3 cm bones
    for name, prop, _ in PICKERS:
        p, s = pb[f"ST {name}"], pb[f"ST {name} valor"]
        for bone_ in (p, s):
            for c in list(bone_.constraints):
                bone_.constraints.remove(c)
        p.custom_shape, p.lock_location = ring, (False, True, False)
        p.lock_rotation = p.lock_scale = (True, True, True)
        c = p.constraints.new("LIMIT_DISTANCE")
        c.target, c.subtarget, c.limit_mode, c.distance = arm, f"ST {name} centro", "LIMITDIST_INSIDE", R
        s.custom_shape, s.lock_location = bar, (True, True, False)
        s.lock_rotation = s.lock_scale = (True, True, True)
        lim = s.constraints.new("LIMIT_LOCATION")
        lim.owner_space, lim.use_min_z, lim.use_max_z, lim.min_z, lim.max_z = "LOCAL", True, True, 0.0, VALUE_MAX * R
        if prop not in sc:
            sc[prop] = (0.0, 0.0, 1.0)
        for i, (bone, ch) in enumerate(((p.name, "LOC_X"), (p.name, "LOC_Z"), (s.name, "LOC_Z"))):
            sc.driver_remove(f'["{prop}"]', i)
            drv = sc.driver_add(f'["{prop}"]', i).driver
            drv.type, drv.expression = "SCRIPTED", f"var / {R}"  # simple expression: no auto-run needed
            t = drv.variables.new()
            t.name, t.type = "var", "TRANSFORMS"
            t.targets[0].id, t.targets[0].bone_target = arm, bone
            t.targets[0].transform_type, t.targets[0].transform_space = ch, "LOCAL_SPACE"
    sol = pb["ST Sol"]
    sol.custom_shape = sun_w
    sol.lock_rotation = sol.lock_scale = (True, True, True)
    # light shines from the sun handle towards the head; the GN modifier reads ST_Light's rotation
    sun = bpy.data.objects.get("ST_Light")
    hb = _head_bone(char_arm)
    if sun and hb:
        for c in list(sun.constraints):
            sun.constraints.remove(c)
        cl = sun.constraints.new("COPY_LOCATION")
        cl.name, cl.target, cl.subtarget = "ST Sol", arm, "ST Sol"
        dt = sun.constraints.new("DAMPED_TRACK")
        dt.name, dt.target, dt.subtarget, dt.track_axis = "ST Cabeza", char_arm, hb, "TRACK_NEGATIVE_Z"


def _is_rig(arm):
    return "DEF-spine.006" in arm.data.bones and "root" in arm.data.bones


def ensure_lighting_panel(context, near):
    """Lighting controls: HSV wheels (Luz/Ambiente) + value sliders + sun handle. Drivers copy each
    picker's position into a scene property and the toon shader converts it to RGB."""
    char_arm = near.find_armature()
    if "ST Panel" in char_arm.data.bones:
        bind_lighting(context, char_arm, char_arm)
        return char_arm
    pan = bpy.data.objects.get(PANEL) or create_panel(context, near, char_arm)
    if _is_rig(char_arm):
        merge_panel(context, pan, char_arm)
        bind_lighting(context, char_arm, char_arm)
        return char_arm
    attach_panel(context, pan, char_arm)
    bind_lighting(context, pan, char_arm)
    return pan


def attach_panel(context, pan, arm):
    """Make the standalone panel follow the character's root bone, keeping where it is now."""
    if pan and arm and "root" in arm.data.bones and (pan.parent, pan.parent_bone) != (arm, "root"):
        _reparent(context, pan, arm, "root")


# ---------- outline (inverted hull) ----------
OUTLINE_SUFFIX = " Outline"
OUTLINE_TINT = (0.19, 0.19, 0.28, 1.0)  # BaseColor of the game's outline materials (MI_*_Outline), times BaseMap
OUTLINE_WIDTH = 0.002  # metres; ~1.5 px at full-body 1080p like the reference videos
# shortcut: width is constant in world space (the game's looks screen-space) and the hull follows
# the mesh normals, not the smoothed normals packed in COL0.rgb; revisit if close-ups look too thick
# or hard edges show cracks.


def build_outline_gn():
    """Duplicate the deformed mesh, push it out along the normal by width * COL0.alpha (the game's
    outline mask: 0 on face/eyes), flip it and give each face its material's outline slot."""
    ng = bpy.data.node_groups.get("ST Outline")
    if ng:
        return ng
    ng = bpy.data.node_groups.new("ST Outline", "GeometryNodeTree")
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    w = sock(ng, "Grosor", "INPUT", "NodeSocketFloat", OUTLINE_WIDTH)
    w.min_value, w.max_value, w.subtype = 0.0, 0.02, "DISTANCE"
    sock(ng, "Primer slot de contorno", "INPUT", "NodeSocketInt", 0)
    nt = ng
    gi = node(nt, "NodeGroupInput", -1000, 0)
    go = node(nt, "NodeGroupOutput", 900, 0)
    col = node(nt, "GeometryNodeInputNamedAttribute", -1000, -300, data_type="FLOAT_COLOR")
    col.inputs["Name"].default_value = "COL0"
    sep = node(nt, "FunctionNodeSeparateColor", -800, -300)
    nt.links.new(col.outputs["Attribute"], sep.inputs[0])
    mask = sep.outputs["Alpha"]
    keep = node(nt, "GeometryNodeDeleteGeometry", -600, 100, domain="FACE")
    nt.links.new(gi.outputs["Geometry"], keep.inputs["Geometry"])
    nt.links.new(math(nt, "LESS_THAN", mask, 0.01, -700, -100), keep.inputs["Selection"])
    nrm = node(nt, "GeometryNodeInputNormal", -600, -200)
    off = node(nt, "ShaderNodeVectorMath", -400, -200, operation="SCALE")
    nt.links.new(nrm.outputs["Normal"], off.inputs[0])
    nt.links.new(math(nt, "MULTIPLY", gi.outputs["Grosor"], mask, -550, -350), off.inputs["Scale"])
    sp = node(nt, "GeometryNodeSetPosition", -200, 100)
    nt.links.new(keep.outputs["Geometry"], sp.inputs["Geometry"])
    nt.links.new(off.outputs[0], sp.inputs["Offset"])
    flip = node(nt, "GeometryNodeFlipFaces", 0, 100)
    nt.links.new(sp.outputs["Geometry"], flip.inputs["Mesh"])
    idx = node(nt, "GeometryNodeInputMaterialIndex", 0, -150)
    smi = node(nt, "GeometryNodeSetMaterialIndex", 200, 100)
    nt.links.new(flip.outputs["Mesh"], smi.inputs["Geometry"])
    nt.links.new(math(nt, "ADD", idx.outputs[0], gi.outputs["Primer slot de contorno"], 100, -150), smi.inputs["Material Index"])
    join = node(nt, "GeometryNodeJoinGeometry", 500, 0)
    nt.links.new(smi.outputs["Geometry"], join.inputs[0])
    nt.links.new(gi.outputs["Geometry"], join.inputs[0])
    nt.links.new(join.outputs[0], go.inputs["Geometry"])
    return ng


def outline_material(src):
    """Dark tint of the source material's BaseMap; only the hull's camera-facing side shows."""
    name = src.name + OUTLINE_SUFFIX
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 600, 0)
    base = next((n.image for n in src.node_tree.nodes if n.type == "TEX_IMAGE" and n.image
                 and n.image.colorspace_settings.name == "sRGB"), None) if src.node_tree else None
    tint = node(nt, "ShaderNodeRGB", -400, -150)
    tint.outputs[0].default_value = OUTLINE_TINT
    colour, alpha = tint.outputs[0], None
    if base:
        tex = node(nt, "ShaderNodeTexImage", -400, 150, image=base)
        colour = mix_rgb(nt, "MULTIPLY", 1.0, tex.outputs["Color"], tint.outputs[0], -150, 50)
        alpha = tex.outputs["Alpha"]
    em = node(nt, "ShaderNodeEmission", 100, 50)
    nt.links.new(colour, em.inputs["Color"])
    # hide the hull's back side (inverted hull) also in Cycles, where backface culling is ignored
    geo = node(nt, "ShaderNodeNewGeometry", 100, 300)
    cut = geo.outputs["Backfacing"]
    if alpha is not None:  # alpha-clipped parts (hair tips, lace) get no outline where they are cut
        cut = math(nt, "MAXIMUM", cut, math(nt, "LESS_THAN", alpha, 0.333, 150, -150), 250, 200)
    tr = node(nt, "ShaderNodeBsdfTransparent", 100, -100)
    mx = node(nt, "ShaderNodeMixShader", 400, 0)
    nt.links.new(cut, mx.inputs[0])
    nt.links.new(em.outputs[0], mx.inputs[1])
    nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    m.use_backface_culling = True
    m.surface_render_method = "DITHERED"
    return m


def ensure_outline(obj):
    me = obj.data
    while me.materials and me.materials[-1] and me.materials[-1].name.endswith(OUTLINE_SUFFIX):
        me.materials.pop()
    originals = list(me.materials)
    for src in originals:
        me.materials.append(outline_material(src))
    mod = obj.modifiers.get("ST Outline") or obj.modifiers.new("ST Outline", "NODES")
    mod.node_group = build_outline_gn()
    outline_input(mod, "Primer slot de contorno").value = len(originals)
    return mod


def outline_input(mod, name):
    # Blender 5.x: modifier inputs live in mod.properties.inputs.<identifier>.value
    return getattr(mod.properties.inputs, mod.node_group.interface.items_tree[name].identifier)


def run(obj, char_dir):
    arm = obj.find_armature()
    mesh_skin = skin_of(obj.name, "")
    tex_idx = index_files(char_dir, ".png")
    json_idx = index_files(char_dir, ".json")
    sun, emp = ensure_rig(arm)
    ensure_lighting_panel(bpy.context, obj)  # after ensure_rig: it aims ST_Light with the sun handle
    toon_g, face_g, gn = build_toon_group(), build_face_group(), build_vectors_gn(sun, emp)
    mod = obj.modifiers.get("ST Light Vectors") or obj.modifiers.new("ST Light Vectors", "NODES")
    mod.node_group = gn
    report = {}
    for slot in obj.material_slots:
        mat = slot.material
        if mat.name.endswith(OUTLINE_SUFFIX):
            continue
        base_name = re.sub(r"\.\d{3}$", "", mat.name)  # Blender adds .001 on name clashes (re-imports, FBX)
        jp = pick(json_idx, base_name, skin_of(base_name, mesh_skin))
        if not jp:
            report[mat.name] = "sin JSON, se deja igual"
            continue
        with open(jp, encoding="utf-8") as fh:
            setup_material(mat, json.load(fh), tex_idx, mesh_skin, face_g, toon_g, report)
    ensure_outline(obj)
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


INERTIA_PROPS = {  # group: (rig property, default influence, panel label)
    # 20% stiffer than Gacha Setup's 0.7 / 0.4: theirs felt too loose on Strinova's chains
    "Hair": ("st_hair_inertia", 0.56, "Inercia pelo"),
    "Bangs": ("st_bangs_inertia", 0.28, "Inercia flequillo"),  # bangs sway half as much as the back hair
    "Clothes": ("st_cloth_inertia", 0.32, "Inercia ropa"),
    "Breast": ("st_breast_inertia", 0.2, "Inercia pecho"),
}


def apply_inertia(rig):
    """Gacha Setup style 'physics': each Hair/Clothes chain bone (and Strinova's chest_l/r chains)
    gets a Damped Track towards its own child. That is a dependency cycle on purpose: Blender
    resolves it with the previous evaluation, so strands trail behind the body while animating,
    which reads as inertia. Unlike Gacha's button it only touches those bones (theirs also hit
    Rigify MCH/IK bones on this rig). Trade-off: the result depends on the frames evaluated
    before, so jumping around the timeline or rendering single frames can differ from playback."""
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="OBJECT")
    colls = rig.data.collections_all
    group = {b.name: c for c in PHYS_COLLECTIONS if c in colls for b in colls[c].bones if b.name not in NOT_PHYSICS}
    group.update({b.name: "Breast" for b in rig.data.bones if re.fullmatch(r"chest_[lr]_\d+", b.name)})
    # Bangs / front locks: hair chains whose tip ends in front of the eyes (rig faces -Y). By where
    # the strand ends, not its name or root: Kanami's hair_f_m2 is rooted behind but falls over the face.
    eyes = [b.head_local.y for b in rig.data.bones if "eye" in b.name.lower() and "ball" in b.name.lower()]
    head = rig.data.bones.get("DEF-spine.006")
    face_y = min(eyes) if eyes else (head.head_local.y - 0.05 if head else None)
    if face_y is not None:
        hair = {n for n, g in group.items() if g == "Hair"}
        tip_y = {}
        for n in hair:  # tip of the chain below each bone
            t = rig.data.bones[n]
            while True:
                kids = sorted((c for c in t.children if c.name in hair), key=lambda c: c.name)
                if not kids:
                    break
                t = kids[0]
            tip_y[n] = t.tail_local.y
        for n in hair:
            r = rig.data.bones[n]
            while r.parent and r.parent.name in hair:
                r = r.parent
            if tip_y[r.name] < face_y + 0.01:
                group[n] = "Bangs"
    for c in PHYS_COLLECTIONS:
        if c in colls:
            colls[c].is_visible = False  # keep only the controllers in view; the sliders drive these chains
    for g, (prop, default, label) in INERTIA_PROPS.items():
        if prop not in rig:
            rig[prop] = default
        rig.id_properties_ui(prop).update(min=0.0, max=1.0, description=f"{label}: cuanto se retrasa y arrastra al animar")

    for pb in rig.pose.bones:  # drop previous versions (Copy Rotation / anchored Damped Track)
        c = pb.constraints.get("ST Inertia")
        if c:
            pb.driver_remove('constraints["ST Inertia"].influence')
            pb.constraints.remove(c)
    old = [b.name for b in rig.data.bones if b.name.startswith(("STI-", "STA-"))]
    if old:
        bpy.ops.object.mode_set(mode="EDIT")
        for n in old:
            rig.data.edit_bones.remove(rig.data.edit_bones[n])
        bpy.ops.object.mode_set(mode="OBJECT")
    if "ST Inertia" in colls:
        rig.data.collections.remove(colls["ST Inertia"])

    # Damped Track aims the bone's Y axis at its child. UEFormat imports Strinova's chain bones
    # pointing elsewhere (not at the child), so tracking would swing every bone ~90 deg at rest.
    # Point each one at its child first (tips continue the chain); heads stay, so the mesh, bound
    # to this same rest pose, does not move.
    kids_of = {n: sorted(ch.name for ch in rig.data.bones[n].children if ch.name in group) for n in group}
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for n in group:
        b = eb[n]
        if kids_of[n]:
            aim = eb[kids_of[n][0]].head - b.head
        elif b.parent and b.parent.name in group:
            aim = (b.head - b.parent.head).normalized() * max(b.length, 0.02)
        else:
            continue
        if aim.length > 1e-4:
            b.tail = b.head + aim
    bpy.ops.object.mode_set(mode="OBJECT")

    chains = 0
    for n, g in group.items():
        kids = kids_of[n]
        if not kids:
            continue  # tip of a chain
        if g == "Breast" and kids_of[kids[0]]:
            continue  # chest: one cycle per side, on the weighted bone; chained cycles made one side jitter
        p = rig.data.bones[n].parent
        chains += not (p and p.name in group)
        c = rig.pose.bones[n].constraints.new("DAMPED_TRACK")
        c.name, c.target, c.subtarget, c.track_axis = "ST Inertia", rig, kids[0], "TRACK_Y"
        drv = c.driver_add("influence").driver
        drv.type = "AVERAGE"
        v = drv.variables.new()
        v.type = "SINGLE_PROP"
        v.targets[0].id, v.targets[0].data_path = rig, f'["{INERTIA_PROPS[g][0]}"]'
    return chains


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


def fix_finger_curl(rig):
    """Gacha's NTE rigger rolls each finger so it curls the way it already bends at rest. Strinova's
    T-pose fingers bend slightly up, so the master's scale-curl (driver (1-sy)*pi on the MCH *_drv
    bones) closed them backwards. A positive curl moves the tip towards the bone's local +Z; with
    the palms facing down in the rest pose that must point down, otherwise flip the driver sign."""
    drivers = rig.animation_data.drivers if rig.animation_data else []
    flipped = []
    for side in (".L", ".R"):
        for f in ("f_index", "f_middle", "f_ring", "f_pinky", "thumb"):  # thumb: Gacha doesn't mirror it for .R
            b = rig.data.bones.get(f"ORG-{f}.01{side}")
            if not b:
                continue
            backwards = (rig.matrix_world.to_3x3() @ b.matrix_local.to_3x3()).col[2].z > 0
            for d in drivers:
                if d.data_path.startswith(f'pose.bones["MCH-{f}.') and f'_drv{side}"]' in d.data_path:
                    expr = d.driver.expression.lstrip("-")
                    d.driver.expression = f"-{expr}" if backwards else expr  # set, not toggle: safe to rerun
            if backwards:
                flipped.append(f + side)
    return flipped


def fix_breasts(context, rig):
    """Rigify's breast.L/R controls move DEF-breast, which no vertex is weighted to: Strinova skins
    the chest to its own chest_l_* / chest_r_* chains, left hanging from the spine. Move the
    breast bones onto each chain (Rigify parks them ~14 cm in front of the body, a bad pivot)
    and hang the chain from ORG-breast, which copies the control."""
    chains = {}
    for b in rig.data.bones:
        m = re.fullmatch(r"chest_([lr])_\d+", b.name)
        if m:
            chains.setdefault(m.group(1).upper(), []).append(b.name)
    sides = [s for s in chains if f"ORG-breast.{s}" in rig.data.bones]
    if not sides:
        return []
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = rig.data.edit_bones
    for s in sides:
        names = sorted(chains[s])
        root = next(eb[n] for n in names if not (eb[n].parent and eb[n].parent.name in names))
        tip = eb[names[-1]].tail.copy()
        for n in (f"breast.{s}", f"ORG-breast.{s}", f"DEF-breast.{s}"):
            if n in eb:
                eb[n].head, eb[n].tail = root.head.copy(), tip
        root.use_connect = False
        root.parent = eb[f"ORG-breast.{s}"]
    bpy.ops.object.mode_set(mode="OBJECT")
    return sides


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
        # Gacha Setup rigs the wrong armature if our lighting panel is in the scene: hide it meanwhile
        pan = bpy.data.objects.get(PANEL)
        pan_colls = list(pan.users_collection) if pan else []
        pan_mw = pan.matrix_world.copy() if pan else None  # its parent skeleton gets moved/replaced
        for c in pan_colls:
            c.objects.unlink(pan)
        try:
            # NTE shares Strinova's hyphenated Bip001 skeleton, so Gacha Setup's NTE rigger maps it as is
            bpy.ops.hoyoverse.rig_character(game_type="NEVERNESS_TO_EVERNESS")
        finally:
            for c in pan_colls:
                c.objects.link(pan)
        rig = obj.find_armature()
        if not rig or "DEF-spine.006" not in rig.pose.bones:
            self.report({"ERROR"}, "Gacha Setup no genero el rig (revisa la consola)")
            return {"CANCELLED"}
        # Strinova's weights are authored for rigid bones. Rigify's B-bones (8-10 segments) bend the
        # mesh differently and, since Gacha's NTE rigger flips the roll of consecutive spine bones,
        # tilting the chest twisted the torso. One segment deforms like the game.
        for b in rig.data.bones:
            if b.name.startswith("DEF-"):
                b.bbone_segments = 1
        fix_finger_curl(rig)
        fix_breasts(context, rig)
        if pan:
            pan.parent = None
            pan.matrix_world = pan_mw
            ensure_lighting_panel(context, obj)  # joins the panel into the new rig
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
        mesh = target_mesh(context)
        omod = mesh.modifiers.get("ST Outline") if mesh else None
        if omod and omod.node_group:
            col.prop(outline_input(omod, "Grosor"), "value", text="Grosor contorno")
        col.operator(STRINOVA_OT_rig.bl_idname, icon="ARMATURE_DATA")
        col.operator(STRINOVA_OT_inertia.bl_idname, icon="FORCE_WIND")
        rig = target_rig(context)
        if rig:
            for prop, _, label in INERTIA_PROPS.values():
                if prop in rig:
                    col.prop(rig, f'["{prop}"]', text=label, slider=True)
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
