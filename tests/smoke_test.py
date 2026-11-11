"""Smoke test: import a character with shading + rig in a clean scene.

Run (from the repo folder):
    blender -b --python tests/smoke_test.py -- "<path to .uemodel or .fbx>"
Exits with code 1 if any check fails.
"""
import bpy, sys, traceback

path = sys.argv[sys.argv.index("--") + 1]
try:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    assert bpy.ops.strinova.import_character(filepath=path) == {"FINISHED"}
    sc = bpy.context.scene
    mesh = next(o for o in sc.objects if o.type == "MESH" and o.find_armature() and o.material_slots)
    rig = mesh.find_armature()
    toon = sum(1 for s in mesh.material_slots if s.material and any(n.type == "GROUP" for n in s.material.node_tree.nodes))
    inertia = sum(1 for pb in rig.pose.bones for c in pb.constraints if c.name == "ST Inertia")
    heads = {o.parent_bone for o in sc.objects if o.name.startswith("ST_Head")}
    print(f"[smoke] {mesh.name}: rig={rig.name} toon={toon}/{len(mesh.material_slots)} inertia={inertia} head={heads}")
    assert rig.name != mesh.name and "DEF-spine.006" in rig.pose.bones, "no se genero el rig"
    assert toon > 0, "ningun material con toon"
    assert inertia > 0, "sin cadenas con inercia"
    assert heads == {"DEF-spine.006"}, "empties de la cabeza mal parentados"
    assert "ST Sol" in rig.data.bones and "st_panel" not in mesh, "panel de iluminacion fuera del rig"
    sun = mesh["st_light"]
    assert {c.target for c in sun.constraints} == {rig}, "ST_Light no sigue al control ST Sol del rig"
    ctrls = {p.name for p in rig.pose.bones if p.name.startswith("ST ") and not p.hide}
    assert ctrls == {"ST Luz", "ST Luz valor", "ST Ambiente", "ST Ambiente valor", "ST Sol"}, f"controles de luz visibles: {ctrls}"
    assert all(not rig.pose.bones[n].use_custom_shape_bone_size for n in ctrls), "formas de control escaladas por el hueso"
    for n in ("Luz", "Ambiente"):  # each wheel sits on its picker (both at rest in the centre)
        wheel = next(c for c in rig.children if c.name.startswith(f"ST Rueda {n}"))
        centre = rig.matrix_world @ rig.pose.bones[f"ST {n}"].head
        gap = (wheel.matrix_world.translation - centre).length
        print(f"[smoke] rueda {n} a {gap:.3f} m de su selector")
        assert gap < 0.01, f"la rueda {n} esta separada de su selector"
    for s in ("l", "r"):
        root = rig.data.bones.get(f"chest_{s}_01")
        assert not root or root.parent.name == f"ORG-breast.{s.upper()}", f"chest_{s}_01 no cuelga del control breast"
    bbones = [b.name for b in rig.data.bones if b.name.startswith("DEF-") and b.bbone_segments > 1]
    assert not bbones, f"huesos de deformacion con B-bones (tuercen la malla): {bbones[:5]}"
    shown = {c.name for c in rig.data.collections_all if c.is_visible and c.bones}
    assert not shown & {"Hair", "Clothes", "Other", "ST Inertia"}, f"huesos que no son controladores visibles: {shown}"
    assert not sc.collection.objects, f"objetos sueltos en la raiz: {[o.name for o in sc.collection.objects]}"
    char_coll = mesh.users_collection[0]
    assert char_coll in rig.users_collection and char_coll.name in sc.collection.children, "personaje fuera de su coleccion"
    print(f"[smoke] coleccion: {char_coll.name}")
    mods = [m.name if m.type == "NODES" else m.type for m in mesh.modifiers]
    print(f"[smoke] modificadores: {mods}")
    assert mods.index("ST Outline") > mods.index("ARMATURE"), "el contorno se evalua antes que el armature"
    # the inertia constraints must not move the mesh in the rest pose
    import numpy as np

    def coords():
        dg = bpy.context.evaluated_depsgraph_get()
        ev = mesh.evaluated_get(dg)
        me = ev.to_mesh()
        c = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", c)
        ev.to_mesh_clear()
        return c.reshape(-1, 3)

    mesh.modifiers["ST Outline"].show_viewport = False
    for _ in range(3):
        sc.frame_set(sc.frame_current)
    on = coords()
    inert = [c for pb in rig.pose.bones for c in pb.constraints if c.name == "ST Inertia"]
    for c in inert:
        c.mute = True
    bpy.context.view_layer.update()
    rest_diff = float(np.linalg.norm(on - coords(), axis=1).max())
    print(f"[smoke] inercia en reposo mueve la malla: {rest_diff:.4f} m")
    assert rest_diff < 0.001, "la fisica deforma la malla en la pose de reposo"
    for c in inert:
        c.mute = False
    # head tracker on by default, without moving the head at rest
    settings = rig.pose.bones["plate-settings"]
    assert settings["Use Head Controller"] == 1, "el seguidor de cabeza no quedo activo"
    settings["Use Head Controller"] = 0
    rig.update_tag()
    bpy.context.view_layer.update()
    head_diff = float(np.linalg.norm(on - coords(), axis=1).max())
    settings["Use Head Controller"] = 1
    rig.update_tag()
    bpy.context.view_layer.update()
    print(f"[smoke] seguidor de cabeza en reposo mueve la malla: {head_diff:.4f} m")
    assert head_diff < 0.001, "el seguidor de cabeza gira la cabeza en reposo"
    # face: gaze leaves the rest pose alone and turns the eye; sorted sliders still drive their keys
    from strinova_toon import face
    for key, sec in (("biyanL", "Ojos"), ("EL_mph48_biyan_L", "Ojos"), ("tongkongbig", "Pupilas"), ("eye_L", "Pupilas"),
                     ("numei_R", "Cejas"), ("B_close_L", "Cejas"), ("zuoZuiJiaoUp", "Boca"), ("M_C_up_L", "Boca"),
                     ("PP", "Fonemas"), ("a2", "Fonemas"), ("M_Aa", "Fonemas"), ("tou_up", "Cabeza y otros"), ("jawdown", "Cabeza y otros"), ("mph37_gulian_L", "Cabeza y otros")):
        assert face.section_of(key) == sec, f"{key} clasificado como {face.section_of(key)}, no {sec}"
    for key, side in (("biyanL", "L"), ("EL_mph48_biyan_R", "R"), ("B_close_L", "L"), ("=_R", "R"), ("eye_L", ""),
                      ("look_left", ""), ("eyeball_small", ""), ("eyeopen", ""), ("cumei", "")):
        assert face.side_of(key) == side, f"{key}: lado {face.side_of(key)!r}, no {side!r}"
    gaze = [c for pb in rig.pose.bones for c in pb.constraints if c.name == "ST Mirada"]
    if "eye_l_ball_01" in rig.data.bones:
        assert len(gaze) == 2, "sin control de mirada"
        for c in gaze:
            c.mute = True
        bpy.context.view_layer.update()
        gaze_diff = float(np.linalg.norm(on - coords(), axis=1).max())
        for c in gaze:
            c.mute = False
        print(f"[smoke] mirada en reposo mueve la malla: {gaze_diff:.4f} m")
        assert gaze_diff < 0.001, "la mirada deforma la malla en reposo"
        eye = rig.pose.bones["eye_l_ball_01"]
        before_eye = eye.matrix.copy()
        rig.pose.bones["Mirada"].location.x = 0.1
        bpy.context.view_layer.update()
        turned = before_eye.to_quaternion().rotation_difference(eye.matrix.to_quaternion()).angle
        print(f"[smoke] mirada 10 cm a un lado gira el ojo {turned * 57.3:.1f} grados")
        assert turned > 0.05, "mover la mirada no gira el ojo"
        rig.pose.bones["Mirada"].location.x = 0
    keys = face.slider_keys(mesh)
    if keys:
        shown = {c.name for c in rig.data.collections_all if c.name.startswith("Cara: ")}
        print(f"[smoke] cara: {len(keys)} sliders en {sorted(shown)}")
        frames = [b for b in rig.data.bones if b.name.startswith("FRAME-ST")]
        assert {"FRAME-ST izquierda", "FRAME-ST derecha"} <= {b.name for b in frames}, "faltan los recuadros de la cara"
        assert all(b.hide_select for b in frames), "los recuadros se pueden seleccionar"
        bone, (_, key) = next(iter(keys.items()))
        rig.pose.bones[bone].location.z = 1.0  # clamped to the slider's top
        bpy.context.view_layer.update()
        value = mesh.data.shape_keys.key_blocks[key].value
        rig.pose.bones[bone].location.z = 0
        assert value > 0.99, f"el slider {bone} ya no mueve {key} ({value})"
    rig["st_physics"] = False  # the panel toggle must zero every inertia influence
    rig.update_tag()
    bpy.context.view_layer.update()
    live = max(c.influence for c in inert)
    rig["st_physics"] = True
    print(f"[smoke] influencia maxima con la fisica apagada: {live:.3f}")
    assert live == 0, "el interruptor de fisica no apaga las restricciones"
    joints = [g.name for g in mesh.vertex_groups if g.name.endswith("_SkinJNT") and not g.name.startswith("Facial_Master")]
    ctrls = [b.name for b in rig.data.bones if any(c.name in ("Cara: Huesos", "Cara: Boca interior") for c in b.collections)]
    print(f"[smoke] huesos faciales: {len(joints)}, con control: {len(ctrls)}")
    assert set(joints) <= set(ctrls), "hay huesos faciales sin control"
    for k in [k for k in rig.keys() if k.startswith("st_show_")]:  # accessory show toggles
        def count():
            rig.update_tag()
            bpy.context.view_layer.update()
            return len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices)
        shown = count()
        rig[k] = False
        hidden = count()
        rig[k] = True
        print(f"[smoke] {k}: {shown} -> {hidden} vertices")
        assert hidden < shown == count(), f"{k} no oculta el accesorio"
    print("[smoke] OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
