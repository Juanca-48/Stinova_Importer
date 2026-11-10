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
    assert "ST Sol" in rig.data.bones and "ST Lighting Panel" not in bpy.data.objects, "panel de iluminacion fuera del rig"
    sun = bpy.data.objects["ST_Light"]
    assert {c.target for c in sun.constraints} == {rig}, "ST_Light no sigue al control ST Sol del rig"
    ctrls = {p.name for p in rig.pose.bones if p.name.startswith("ST ") and not p.hide}
    assert ctrls == {"ST Luz", "ST Luz valor", "ST Ambiente", "ST Ambiente valor", "ST Sol"}, f"controles de luz visibles: {ctrls}"
    assert all(not rig.pose.bones[n].use_custom_shape_bone_size for n in ctrls), "formas de control escaladas por el hueso"
    for s in ("l", "r"):
        root = rig.data.bones.get(f"chest_{s}_01")
        assert not root or root.parent.name == f"ORG-breast.{s.upper()}", f"chest_{s}_01 no cuelga del control breast"
    bbones = [b.name for b in rig.data.bones if b.name.startswith("DEF-") and b.bbone_segments > 1]
    assert not bbones, f"huesos de deformacion con B-bones (tuercen la malla): {bbones[:5]}"
    shown = {c.name for c in rig.data.collections_all if c.is_visible and c.bones}
    assert not shown & {"Hair", "Clothes", "Other", "ST Inertia"}, f"huesos que no son controladores visibles: {shown}"
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
    print("[smoke] OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
