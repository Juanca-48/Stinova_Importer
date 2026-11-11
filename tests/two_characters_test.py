"""Two characters in one scene: each keeps its own rig, materials, sun, head empties and lighting.

Run (from the repo folder):
    blender -b --python tests/two_characters_test.py -- "<first .uemodel/.fbx>" "<second .uemodel/.fbx>"
Exits with code 1 if any check fails.
"""
import bpy, sys, traceback

paths = sys.argv[sys.argv.index("--") + 1:]
try:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    meshes, shapes, linked = [], [], set()
    for p in paths:
        linked = {o.name for o in bpy.data.objects if o.users_collection}
        before = set(bpy.data.objects)
        assert bpy.ops.strinova.import_character(filepath=p) == {"FINISHED"}
        meshes.append(next(o for o in bpy.data.objects if o not in before and o.type == "MESH" and o.get("st_light")))
        shapes.append({pb.name: pb.custom_shape for pb in meshes[-1].find_armature().pose.bones})
    rigs = [m.find_armature() for m in meshes]
    first_now = {pb.name: pb.custom_shape for pb in rigs[0].pose.bones}
    changed = {n: (getattr(shapes[0][n], "name", None), getattr(s, "name", None)) for n, s in first_now.items() if shapes[0].get(n) != s}
    assert not changed, f"el segundo rig cambio las formas de control del primero: {list(changed.items())[:8]}"
    lost = [n for n in linked if n not in bpy.data.objects or not bpy.data.objects[n].users_collection]
    assert not lost, f"objetos del primer personaje fuera de la escena: {lost[:5]}"
    print(f"[2pj] {[(m.name, r.name) for m, r in zip(meshes, rigs)]}")
    assert len({r for r in rigs}) == len(rigs), "dos personajes comparten rig"
    for m, r in zip(meshes, rigs):
        assert "DEF-spine.006" in r.data.bones, f"{m.name}: sin rig"
        assert any(c.name == "ST Inertia" for pb in r.pose.bones for c in pb.constraints), f"{m.name}: sin fisica"
        # "ST <bone>" groups are not weights: they mark an accessory for its show toggle (ST Ocultar <bone>)
        missing = {g.name for g in m.vertex_groups if not g.name.startswith("ST ")} - {b.name for b in r.data.bones}
        assert not missing, f"{m.name}: grupos de vertices sin hueso en su rig: {sorted(missing)[:5]}"
        groups = {n.node_tree for s in m.material_slots if s.material for n in s.material.node_tree.nodes if n.type == "GROUP"}
        assert groups and None not in groups, f"{m.name}: materiales sin node group"
        mod = m.modifiers["ST Light Vectors"]
        objs = {getattr(mod.properties.inputs, i.identifier).value for i in mod.node_group.interface.items_tree
                if i.item_type == "SOCKET" and i.socket_type == "NodeSocketObject"}
        assert objs == {m["st_light"], m["st_head_origin"], m["st_head_forward"], m["st_head_up"]}, f"{m.name}: vectores de otro personaje"
        assert {e.parent for e in objs if e.type == "EMPTY"} == {r}, f"{m.name}: empties de la cabeza en otro rig"
        assert {c.target for c in m["st_light"].constraints} == {r}, f"{m.name}: el sol sigue a otro rig"
        targets = {v.targets[0].id for d in m.animation_data.drivers for v in d.driver.variables}
        assert targets == {r}, f"{m.name}: colores de luz movidos por {targets}"
        assert "st_panel" not in m, f"{m.name}: panel de iluminacion fuera del rig"
        assert r.users_collection[0] in m.users_collection, f"{m.name}: rig fuera de la coleccion del personaje"
    # moving one character's light picker changes only that character's colour
    a, b = meshes[0], meshes[1]
    vb = tuple(b["st_light_pick"])
    rigs[0].pose.bones["ST Luz valor"].location.z = 0.0
    bpy.context.view_layer.update()
    print(f"[2pj] luz: {tuple(a['st_light_pick'])} / {tuple(b['st_light_pick'])}")
    assert a["st_light_pick"][2] == 0.0 and tuple(b["st_light_pick"]) == vb, "el panel de un personaje cambia al otro"
    print("[2pj] OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
