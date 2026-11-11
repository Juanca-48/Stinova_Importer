"""Paper version on the 3D character's rig and the 3D/paper switch.

Run (from the repo folder):
    blender -b --python tests/paper_switch_test.py -- "<3D .uemodel>" "<Mesh2D .uemodel>" [render.png]
    blender -b --python tests/paper_switch_test.py -- "<3D .uemodel>" -     (both in one import)
    blender -b --python tests/paper_switch_test.py -- "<skin folder>" -     (the folder: both found in it)
Exits with code 1 if any check fails. With a render path it also renders the posed 3D and paper versions.
"""
import bpy, sys, traceback, math
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
try:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    together = args[1] == "-"  # "-": one import with "Incluir version de papel", which finds the Mesh2D model itself
    assert bpy.ops.strinova.import_character(filepath=args[0], do_paper=together) == {"FINISHED"}
    host = next(o for o in sc.objects if o.type == "MESH" and o.get("st_light") and not o.get("st_paper"))
    rig = host.find_armature()
    n_colls = len(bpy.data.collections)
    if not together:
        assert bpy.ops.strinova.import_character(filepath=args[1]) == {"FINISHED"}
    paper = next(o for o in sc.objects if o.get("st_paper"))
    print(f"[papel] {paper.name} en {paper.find_armature().name}, colecciones {[c.name for c in paper.users_collection]}")
    assert paper.find_armature() == rig and paper.parent == rig, "el papel no usa el rig del 3D"
    assert paper.users_collection == host.users_collection, "el papel no quedo en la coleccion del personaje"
    assert sum(1 for o in bpy.data.objects if o.type == "ARMATURE") == 1, "quedo un esqueleto suelto"
    assert len(bpy.data.collections) == n_colls, "se creo otra coleccion"
    missing = [g.name for g in paper.vertex_groups if g.name not in rig.data.bones]
    assert not missing, f"grupos del papel sin hueso: {missing}"
    mod = paper.modifiers["ST Light Vectors"]
    sol = next(i for i in mod.node_group.interface.items_tree if getattr(i, "name", "") == "Sol")
    assert getattr(mod.properties.inputs, sol.identifier).value == host["st_light"], "el papel tiene otro sol"
    assert {v.targets[0].id for d in paper.animation_data.drivers if d.data_path.startswith('["st_')
            for v in d.driver.variables} == {rig}, "los colores del papel no salen del panel del rig"

    def shown(o):  # the switch empties the hidden mesh (ST Ocultar modifier), viewport and render
        mod = o.modifiers["ST Ocultar"]
        assert o.modifiers[-1] == mod, f"{o.name}: ST Ocultar no es el ultimo modificador"
        ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
        assert mod.show_viewport == mod.show_render
        return len(ev.data.vertices) > 0

    def flip(on):
        rig["st_paper"] = on
        rig.update_tag()
        bpy.context.view_layer.update()

    flip(False)
    assert shown(host) and not shown(paper), "con el interruptor apagado debe verse el 3D"
    flip(True)
    assert shown(paper) and not shown(host), "con el interruptor encendido debe verse el papel"

    def coords(ob):
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        c = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", c)
        ev.to_mesh_clear()
        return (np.array(ob.matrix_world) @ np.c_[c.reshape(-1, 3), np.ones(len(c) // 3)].T).T[:, :3]

    rest = np.array([paper.matrix_world @ v.co for v in paper.data.vertices])
    drift = float(np.linalg.norm(coords(paper) - rest, axis=1).max())
    print(f"[papel] en reposo se mueve {drift:.4f} m")
    assert drift < 0.001, "el rig deforma el papel en reposo"
    # a pose moves both versions alike: compare where the head goes
    torso = rig.pose.bones["torso"]
    torso.rotation_mode = "XYZ"
    torso.rotation_euler = (0, 0, math.radians(35))
    bpy.context.view_layer.update()
    flip(False)
    h3 = coords(host)
    flip(True)
    p2 = coords(paper)
    top3, top2 = h3[h3[:, 2] > np.percentile(h3[:, 2], 97)].mean(0), p2[p2[:, 2] > np.percentile(p2[:, 2], 97)].mean(0)
    print(f"[papel] cabeza girada: 3D {top3.round(3)} / papel {top2.round(3)}")
    assert np.linalg.norm(top3[:2] - top2[:2]) < 0.05, "el papel no sigue la pose del 3D"
    if len(args) > 2:
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        sc.collection.objects.link(cam)
        cam.location, cam.rotation_euler = (0, -3.6, 0.9), (math.radians(90), 0, 0)
        sc.camera = cam
        sc.render.resolution_x, sc.render.resolution_y = 360, 420
        for on in (False, True):
            flip(on)
            sc.render.filepath = args[2].replace(".png", "_papel.png" if on else "_3d.png")
            bpy.ops.render.render(write_still=True)
    print("[papel] OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
