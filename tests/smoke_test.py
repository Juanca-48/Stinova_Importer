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
    print("[smoke] OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)
