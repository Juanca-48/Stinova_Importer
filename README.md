# Stinova_Importer

Add-on de Blender para importar personajes de **Strinova** exportados con FModel y dejarlos listos: toon shading, rig con controles y física por constraints en pelo y ropa.

Probado en Blender 5.2: importación y shading con las 91 skins exportadas de Kanami, Chiyo, Aika (Eika), Flavia y Nora; rig con Kanami, Michele y Aika.

## Qué hace

Panel **Strinova** en el viewport 3D (tecla N):

| Botón | Qué hace |
|---|---|
| **Importar personaje** | Importa un `.uemodel` (UEFormat) o `.fbx`. Detecta la carpeta del personaje y, si está marcado, aplica shading y rig en el mismo paso. |
| **Aplicar Toon Shading** | Reconstruye los materiales a partir de los JSON y PNG de FModel (toon con luz del sol, cara con SDF, normal map, matcap). Crea `ST_Light` y los empties de la cabeza. |
| **Controles de iluminación** | Los crea el shading junto al personaje y, al generar el rig, pasan a ser parte de él (colección de huesos *Iluminacion*), así que se animan en la misma acción que el personaje. **Ruedas HSV** *Luz* (lado iluminado) y *Ambiente* (sombra): la posición del selector da tono y saturación, y la barra, el valor. **Sol** (`ST Sol`): la luz llega desde donde esté este control hacia la cabeza, y mueve las sombras del cuerpo y de la cara. Todo sigue al hueso `root`. Presets *Neutral*, *Galería (fría)* y *Atardecer* en el panel N. |
| **Rig + Física** | Genera un rig Rigify con el rigger NTE de Gacha Setup (comparte el esqueleto `Bip001-` de Strinova) y aplica la física por constraints. |
| **Física por Constraints** | Aplica solo la física a un rig ya generado. Sliders *Inercia pelo* / *Inercia ropa* (0 = rígido, 1 = no sigue). |

La física es inercia sin simulación: las cadenas de pelo y ropa siguen solo en parte el giro de la cabeza y el torso, en tiempo real y sin reproducir la línea de tiempo.

## Requisitos

- Blender 5.2
- **Gacha Setup** (`setup_wizard`): para el rig
- **UEFormat** v10 o superior: solo para importar `.uemodel`; con `.fbx` no hace falta
- Exportación de FModel con la estructura `...\Characters\<Nombre>\<Skin>\Mesh3D\` (modelo, `Materials\*.json`, `Textures\*.png`)

## Instalación

**Para desarrollar** (Blender carga el add-on directo desde el repo): cierra Blender y en PowerShell ejecuta

```powershell
New-Item -ItemType Junction `
  -Path "$env:APPDATA\Blender Foundation\Blender\5.2\scripts\addons\strinova_toon" `
  -Target "<ruta del repo>\strinova_toon"
```

Después actívalo en *Preferences > Add-ons > Strinova Toon Setup*. Cada cambio en el repo se ve al reiniciar Blender o recargar el add-on.

**Para instalar en otro PC**: genera el zip y usa *Preferences > Add-ons > Install from Disk*:

```
git archive -o strinova_toon.zip HEAD strinova_toon/
```

## Prueba

```
blender -b --python tests/smoke_test.py -- "D:\...\Characters\Kanami\S215\Mesh3D\SK_Kanami_Mesh_S215.uemodel"
```

Termina con `[smoke] OK`, o con código de salida 1 si algo falla.

## Limitaciones conocidas

- **Un personaje por escena**: `ST_Light` y los empties de la cabeza son compartidos.
- **Sombra plana**: el color de sombra es un tinte fijo, no el atlas de rampas del juego (`RampID`). `Mask1` y `Mask2` todavía no se usan.
- **Hueso de la cabeza fijo**: se busca como `Bip001-Head` o `DEF-spine.006`.
- **FBX de otras herramientas sin probar**: un FBX de Unreal Editor o de otros conversores puede traer escala en cm o los ejes de los huesos cambiados. Los FBX exportados desde Blender funcionan.
- **Huesos sin reacción**: la inercia no reacciona al mover el `root` ni al levantar las piernas (la falda cuelga de la cadera).
