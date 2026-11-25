# Strinova Toon Setup

**English** · [Español](README.es.md)

Blender add-on that imports **Strinova** characters and gets them ready to animate and render with a single button.

It works with both model formats, **`.uemodel`** and **`.fbx`**, wherever they come from.

## What it does

- **Imports** `.uemodel` and `.fbx`, or a skin's whole folder: brings in the 3D model and its paper version together. Textures near the model are found by themselves.
- **Toon shading** like in the game: materials rebuilt from the textures, smooth face shadows and outlines.
- **Per-character lighting**: a sun moved with a control, hard and soft light and shadow colors, rim light and shadow softness. The colors are set with wheels in the rig or in the side panel, for the selected character only.
- **Full rig** with [Gacha Setup](https://github.com/PaoloESAN/gacha-setup), with elbows and knees by rotation or by poles, plus hair, clothes and chest physics you turn on with a checkbox.
- **Tidy face**: expression controls grouped into Eyes, Pupils, Brows, Mouth, Lips and Head, with colors, a look-at control and blinking.
- **Paper version**: switch between the 3D model and the paper one in a single frame, like in the game.
- **Accessories**: masks and hats with their own bone and a switch to show or hide them.
- **Several characters** in the same scene, each with its own light.
- **Weapons** with their own button: body, sight, pendant and magazine assembled, with their shading, and a button to put them in the character's hand.

## Requirements

| | |
|---|---|
| **Blender 5.2 or 5.3** | |
| **[Gacha Setup](https://github.com/PaoloESAN/gacha-setup/releases)** | Required for the rig: this add-on uses its rigger. |
| **[UEFormat](https://github.com/h4lfheart/UEFormat)** | Only for importing `.uemodel` (not needed for `.fbx`). |

## Download and installation

1. Install **[Gacha Setup](https://github.com/PaoloESAN/gacha-setup/releases)** and, if you'll use `.uemodel`, **[UEFormat](https://github.com/h4lfheart/UEFormat)**, following each one's instructions.
2. Download `strinova_toon-vX.Y.Z.zip` from the latest version in **[Releases](https://github.com/Juanca-48/Stinova_Importer/releases/latest)**. Don't unzip it.
3. In Blender: *Edit > Preferences > Add-ons > Install from Disk* and pick that zip.
4. Enable **Strinova Toon Setup** and check that **Gacha Setup** and **Rigify** (bundled with Blender) are enabled too.

To update, install the new version's zip the same way and restart Blender.

The panel is in the 3D viewport, **Strinova** tab (N key). It's in English, or in Spanish when Blender's interface is.

The full user guide, with every option, is in [INSTRUCTIONS.txt](INSTRUCTIONS.txt).

## License

[GPL-3.0-or-later](LICENSE), the same as Blender and [Gacha Setup](https://github.com/PaoloESAN/gacha-setup), whose rigger this add-on uses to build the rig.
