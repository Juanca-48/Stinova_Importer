"""The few animated effect materials on the characters' own meshes: Celestia's ribbon, the sparkles on Flavia's
train, the breathing stars of Eika and Kokona, and the game's general effect material ("layer": the glow over
Flavia's flames, Kanami's wings, MoBai's cloak, Meredith's letters), whose switches say what it does. The game's node graphs aren't in its data: each look is built
from the material's textures and colours to match the reference videos, and moves with the scene's frame.
shortcut: the ribbon's waving (WP_*, moved in the vertex shader) and the sparkles' dissolve are left out.
"""
import os
from math import tau
from . import common
from .shading import frame, math, mix_rgb, node, pick, shader_out, soft_step, tex, vmath

KINDS = {"ribbon": ("T_rgb", "AlphaMaskB_Tex", "AlphaMaskB_Tex03", "Color_T3", "MainTexture"),
         "sparkle": ("MainTexture", "Noise"), "breath": ("MainTex",), "layer": ("MainTexture",)}
OPTIONAL = ("A_Mask", "MainTexUVNoise_Tex", "AlphaMaskA_Tex", "AlphaMaskB_Tex", "DissolveTex", "DissolveMask")


def kind_of(data):
    """Which effect a material without a colour texture is, or None."""
    t = data.get("Textures", {})
    if t.get("T_rgb") and t.get("AlphaMaskB_Tex"):
        return "ribbon"
    if t.get("T-Color") and t.get("Noise"):
        return "sparkle"
    if t.get("MainTexture") and any(k.startswith("IF_") for k in data.get("Switches", {})):
        return "layer"
    return "breath" if t.get("MainTex") and "BreathBrightColor" in data.get("Colors", {}) else None


def find(entry, tex_idx, skin):
    """A texture's file: among the character's, or in the FModel export the preferences know (the effects'
    textures are shared, outside the characters' folders)."""
    path = pick(tex_idx, entry["ObjectName"].split("'")[1], skin)
    root, rel = common.fmodel_root(), entry.get("ObjectPath", "").partition("/PaperMan/")[2]
    if not path and root and rel:
        path = os.path.join(os.path.dirname(root), *rel.rsplit(".", 1)[0].split("/")) + ".png"
    return path if path and os.path.isfile(path) else None


def seconds(nt, speed, x, y):
    """Value node: the scene's time in seconds times `speed`."""
    v = node(nt, "ShaderNodeValue", x, y)
    d = v.outputs[0].driver_add("default_value").driver
    d.type = "SCRIPTED"
    var = d.variables.new()
    var.name, var.type = "fps", "CONTEXT_PROP"
    var.targets[0].context_property, var.targets[0].data_path = "ACTIVE_SCENE", "render.fps"
    d.expression = f"frame / fps * {speed}"  # simple expression: no auto-run needed
    return v.outputs[0]


def panned(nt, tiling, u_speed, v_speed, x, y):
    """UV times `tiling`, moving `u_speed`, `v_speed` per second."""
    uv = node(nt, "ShaderNodeUVMap", x, y)
    scaled = vmath(nt, "MULTIPLY", uv.outputs[0], None, x + 180, y)
    scaled.inputs[1].default_value = (*tiling, 1.0)
    move = node(nt, "ShaderNodeCombineXYZ", x + 180, y - 200)
    for i, s in enumerate((u_speed, -v_speed)):  # V grows down in the game
        if s:
            nt.links.new(seconds(nt, s, x, y - 200 - 100 * i), move.inputs[i])
    return vmath(nt, "ADD", scaled.outputs[0], move.outputs[0], x + 360, y).outputs[0]


def bright(c, white):
    """A (possibly HDR) parameter colour as a plain one, part of it white."""
    top = max(c["R"], c["G"], c["B"], 0.001)
    return tuple((max(c[k], 0.0) / top) ** 1.8 * (1 - white) + white for k in "RGB") + (1.0,)  # power: pale in the data, vivid on screen


def red(nt, colour, x, y, channel=0):
    sep = node(nt, "ShaderNodeSeparateColor", x, y)
    nt.links.new(colour, sep.inputs[0])
    return sep.outputs[channel]


def ribbon(nt, files, sca, cols):
    t_rgb = tex(nt, files["T_rgb"], "Non-Color", -600, 400).outputs["Color"]
    edge, body = red(nt, t_rgb, -300, 400), red(nt, t_rgb, -300, 250, 2)
    tiling = cols.get("AlphaMaskB_UVTiling", {"R": 2.0, "G": 0.8})
    veil = red(nt, tex(nt, files["AlphaMaskB_Tex"], "Non-Color", -600, 100, panned(
        nt, (tiling["R"], tiling["G"]), sca.get("AlphaMaskB_UV_Uspeed", 0.3), sca.get("AlphaMaskB_UV_Vspeed", 0.1), -1200, 100)).outputs["Color"], -300, 100)
    tiling = cols.get("AlphaMaskB_UVTiling03", {"R": 10.0, "G": 2.0})
    dust = red(nt, tex(nt, files["AlphaMaskB_Tex03"], "Non-Color", -600, -200, panned(
        nt, (tiling["R"], tiling["G"]), sca.get("AlphaMaskB_UV_Uspeed_03", -0.3), 0.0, -1200, -200)).outputs["Color"], -300, -200)
    sheen = tex(nt, files["Color_T3"], "sRGB", -600, -500).outputs["Color"]
    sweep = red(nt, tex(nt, files["MainTexture"], "Non-Color", -600, -800, panned(
        nt, (1.0, 1.0), sca.get("MainTexUV_Uspeed", -0.35), 0.0, -1200, -800)).outputs["Color"], -300, -800)
    col = mix_rgb(nt, "MIX", 0.1, bright(cols.get("Color_ALL", {"R": 1, "G": 1, "B": 1}), 0.08), sheen, 0, 100)
    shine = math(nt, "ADD", math(nt, "MULTIPLY", math(nt, "MULTIPLY", veil, veil, 0, -100), 0.2, 150, -100), math(nt, "MULTIPLY", dust, 0.8, 0, -250), 300, -100)
    col = mix_rgb(nt, "ADD", math(nt, "ADD", shine, math(nt, "MULTIPLY", sweep, 0.1, 150, -400), 450, -100), col, (1.0, 1.0, 1.0, 1.0), 600, 100)
    col = mix_rgb(nt, "MIX", edge, col, bright(cols.get("E", {"R": 1, "G": 1, "B": 1}), 0.35), 750, 100)
    inner = math(nt, "MULTIPLY", body, math(nt, "ADD", math(nt, "MULTIPLY", shine, 0.6, 450, -500), 0.5, 600, -500), 750, -500)
    return col, math(nt, "MINIMUM", math(nt, "MAXIMUM", inner, math(nt, "MULTIPLY", edge, 0.95, 750, -650), 900, -500), 1.0, 1050, -500)


def sparkle(nt, files, sca, cols):
    tiling = cols.get("MainTexture_Tex_UV", {"R": 0.6, "G": 1.3})
    stars = red(nt, tex(nt, files["MainTexture"], "Non-Color", -600, 200, panned(nt, (tiling["R"] * 2, tiling["G"] * 2), 0.0, 0.0, -1200, 200)).outputs["Color"], -300, 200)
    # they twinkle as the noise drifts over them
    noise = red(nt, tex(nt, files["Noise"], "Non-Color", -600, -200, panned(nt, (2.0, 3.0), 0.05, -0.03, -1200, -200)).outputs["Color"], -300, -200)
    star = math(nt, "MULTIPLY", soft_step(nt, stars, 0.35, 0.15, 0, 200), soft_step(nt, noise, 0.35, 0.25, 0, -200), 400, 100)
    if files.get("A_Mask"):
        star = math(nt, "MULTIPLY", star, red(nt, tex(nt, files["A_Mask"], "Non-Color", -600, -500).outputs["Color"], -300, -500), 600, 0)
    col = node(nt, "ShaderNodeRGB", 400, 400)
    col.outputs[0].default_value = bright(cols.get("Color", {"R": 1, "G": 1, "B": 1}), 0.75)
    return col.outputs[0], star


def breath(nt, files, sca, cols):
    t = tex(nt, files["MainTex"], "sRGB", -600, 200)
    wave = math(nt, "SINE", seconds(nt, sca.get("BreathSpeed", 1.0) * tau, -600, -200), None, -400, -200)
    amount = math(nt, "MULTIPLY", math(nt, "ADD", math(nt, "MULTIPLY", wave, 0.5, -200, -200), 0.5, 0, -200), sca.get("BreathAmplitude", 1.0), 200, -200)
    rgb = lambda name, default: tuple(cols[name][k] for k in "RGB") + (1.0,) if name in cols else (*default, 1.0)
    glow = mix_rgb(nt, "MIX", amount, rgb("BreathDarkColor", (0, 0, 0)), rgb("BreathBrightColor", (1, 1, 1)), 400, -100, clamp=False)
    light = mix_rgb(nt, "ADD", 1.0, rgb("BaseColor", (0.5, 0.5, 0.5)), glow, 600, 0, clamp=False)
    return mix_rgb(nt, "MULTIPLY", 1.0, t.outputs["Color"], light, 800, 100, clamp=False), t.outputs["Alpha"]


def channel(nt, t, weights, x, y):
    """Dot product of a texture's RGBA and `weights`, a colour parameter used as a channel picker."""
    k = max("RGBA", key=lambda c: weights[c])
    return t.outputs["Alpha"] if k == "A" else red(nt, t.outputs["Color"], x, y, "RGB".index(k))


def layer(nt, files, sca, cols, sw):
    """Colour and strength of the general effect material."""
    pair = lambda name: (cols[name]["R"], cols[name]["G"]) if name in cols else (1.0, 1.0)
    speed = lambda name: (sca.get(f"{name}_Uspeed", 0.0), sca.get(f"{name}_Vspeed", 0.0))
    one = {"R": 1.0, "G": 0.0, "B": 0.0, "A": 0.0}
    uv = panned(nt, pair("MainTexUV_Tiling"), *(speed("MainTexUV") if sw.get("IF_MainTexUV_Speed") else (0.0, 0.0)), -1400, 300)
    if sw.get("IF_MainTexUV_Noise") and files.get("MainTexUVNoise_Tex"):
        n = tex(nt, files["MainTexUVNoise_Tex"], "Non-Color", -1500, 0, panned(nt, pair("MainTexUVNoise_Tiling"), *speed("MainTexUVNoise"), -2100, 0))
        push = math(nt, "MULTIPLY", red(nt, n.outputs["Color"], -1200, 0), sca.get("MainTexUVNoise_Intensity", 0.1), -1000, 0)
        both = node(nt, "ShaderNodeCombineXYZ", -850, 0)
        nt.links.new(push, both.inputs[0])
        nt.links.new(push, both.inputs[1])
        uv = vmath(nt, "ADD", uv, both.outputs[0], -700, 200).outputs[0]
    main = tex(nt, files["MainTexture"], "sRGB", -500, 300, uv)
    strength = channel(nt, main, cols.get("MainTex_RGBChannelAsAlpha", one), -200, 100) if sw.get("IF_MainTex_RGBChannelAsAlpha") else main.outputs["Alpha"]
    col = main.outputs["Color"]
    r = cols.get("MainTex_Refine") if sw.get("IF_MainTex_Refine") else None
    if r:  # mix of the texture and its power: contrast
        g = node(nt, "ShaderNodeGamma", -200, 400)
        nt.links.new(col, g.inputs[0])
        g.inputs[1].default_value = r["G"]
        col = mix_rgb(nt, "MIX", r["A"], col, g.outputs[0], 0, 400)
    if not sw.get("IF_NoColor") and "Color" in cols:
        col = mix_rgb(nt, "MULTIPLY", 1.0, col, tuple(cols["Color"][k] for k in "RGB") + (1.0,), 200, 400, clamp=False)
    for m in ("A", "B"):
        if sw.get("IF_AlphaMask" if m == "A" else "IF_AlphaMaskB") and files.get(f"AlphaMask{m}_Tex"):
            y = -300 if m == "A" else -600
            uv = panned(nt, pair(f"AlphaMask{m}_UVTiling"), *speed(f"AlphaMask{m}_UV"), -1200, y)
            t = cols.get(f"AlphaMask{m}_UVTiling", {"B": 0.0, "A": 0.0})
            if t["B"] or t["A"]:  # the tiling's other half is an offset
                uv = vmath(nt, "ADD", uv, None, -700, y)
                uv.inputs[1].default_value = (t["B"], t["A"], 0.0)
                uv = uv.outputs[0]
            mask = channel(nt, tex(nt, files[f"AlphaMask{m}_Tex"], "Non-Color", -500, y, uv), cols.get(f"AlphaMask{m}_AlphaChannel", one), -200, y)
            strength = math(nt, "MULTIPLY", strength, math(nt, "MULTIPLY", mask, sca.get(f"Mask{m}_Intensity", 1.0), 0, y), 200, y)
    if sw.get("IF_Dissolve") and files.get("DissolveTex") and files.get("DissolveMask"):
        n = red(nt, tex(nt, files["DissolveTex"], "Non-Color", -500, -900, panned(nt, pair("DissolveTexUV_Tiling"), *speed("DissolveTexUV"), -1200, -900)).outputs["Color"], -200, -900)
        edge = math(nt, "ADD", red(nt, tex(nt, files["DissolveMask"], "Non-Color", -500, -1200).outputs["Color"], -200, -1200),
                    math(nt, "MULTIPLY", n, sca.get("DissolveNoise_Intensity", 0.0), 0, -900), 200, -1000)
        left = math(nt, "SUBTRACT", edge, sca.get("Dissolve(0-1)", 0.0), 400, -1000)
        if sw.get("IF_DsvOutLine") and "Color" in cols:  # a rim of the colour along the burnt edge
            core = math(nt, "MULTIPLY", math(nt, "SUBTRACT", left, sca.get("DsvOutline", 0.0) * 0.5, 600, -800), sca.get("DsvOutline_Contrast", 1.0), 800, -800)
            core = math(nt, "MINIMUM", math(nt, "MAXIMUM", core, 0.0, 1000, -800), 1.0, 1100, -800)
            col = mix_rgb(nt, "MIX", core, tuple(cols["Color"][k] for k in "RGB") + (1.0,), col, 1200, 300, clamp=False)
        edge = math(nt, "MULTIPLY", left, sca.get("Dissolve_Contrast", 1.0), 600, -1000)
        strength = math(nt, "MULTIPLY", strength, math(nt, "MINIMUM", math(nt, "MAXIMUM", edge, 0.0, 800, -1000), 1.0, 1000, -1000), 1100, -600)
    return col, math(nt, "MINIMUM", math(nt, "MAXIMUM", strength, 0.0, 1200, -300), 1.0, 1300, -300)


def setup(mat, data, kind, tex_idx, skin, report):
    """Build the effect `kind` on `mat`. Without one of its textures it is transparent: as imported it would
    show the mesh's grey vertex colours."""
    textures = data["Textures"]
    files = {k: find(textures[k], tex_idx, skin) for k in KINDS[kind] + OPTIONAL if textures.get(k)}
    nt = mat.node_tree
    blend = data.get("Properties", {}).get("BasePropertyOverrides", {}).get("BlendMode")
    nt.animation_data_clear()
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", 1900, 0)
    if all(files.get(k) for k in KINDS[kind]):
        args = (nt, files, data.get("Scalars", {}), data.get("Colors", {}))
        col, alpha = layer(*args, data.get("Switches", {})) if kind == "layer" else {"ribbon": ribbon, "sparkle": sparkle, "breath": breath}[kind](*args)
        if blend == "BLEND_Additive":
            em = node(nt, "ShaderNodeEmission", 1450, 100)
            nt.links.new(col, em.inputs["Color"])
            nt.links.new(alpha, em.inputs["Strength"])
            add = node(nt, "ShaderNodeAddShader", 1650, 0)
            nt.links.new(em.outputs[0], add.inputs[0])
            nt.links.new(node(nt, "ShaderNodeBsdfTransparent", 1450, -100).outputs[0], add.inputs[1])
            nt.links.new(add.outputs[0], out.inputs["Surface"])
        else:
            if blend == "BLEND_Masked":
                alpha = math(nt, "GREATER_THAN", alpha, 0.333, 1400, -300)
            shader_out(nt, col, alpha, out, 1450, 0)
        for n in nt.nodes:
            if n.type == "TEX_IMAGE":
                n.image.alpha_mode = "CHANNEL_PACKED"
    else:
        tr = node(nt, "ShaderNodeBsdfTransparent", 1250, 0)
        nt.links.new(tr.outputs[0], out.inputs["Surface"])
    frame(nt, f"Effect: {kind}", "color", [n for n in nt.nodes if n.type != "FRAME"])
    mat.surface_render_method = "BLENDED" if blend in ("BLEND_Translucent", "BLEND_Additive") else "DITHERED"
    mat.use_backface_culling = False
    mat["st_effect"] = kind  # no outline
    lost = [textures[k]["ObjectName"].split("'")[1] for k in KINDS[kind] if not files.get(k)]
    report[mat.name] = {"tipo": f"efecto {kind}", "texturas": [os.path.basename(p) for p in files.values() if p], "faltan": lost}
