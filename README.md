# Stinova_Importer

Add-on de Blender para importar personajes de **Strinova** exportados con FModel y dejarlos listos: toon shading, rig con controles y física por constraints en pelo y ropa.

Probado en Blender 5.2: importación y shading con las 91 skins exportadas de Kanami, Chiyo, Aika (Eika), Flavia y Nora; rig con Kanami, Michele y Aika.

## Qué hace

Panel **Strinova** en el viewport 3D (tecla N):

| Botón | Qué hace |
|---|---|
| **Importar personaje** | Importa un `.uemodel` (UEFormat) o `.fbx`. Detecta la carpeta del personaje y, si está marcado, aplica shading y rig en el mismo paso. |
| **Aplicar Toon Shading** | Reconstruye los materiales a partir de los JSON y PNG de FModel (toon con luz del sol, cara con SDF, normal map, matcap). Crea `ST_Light` y los empties de la cabeza. Añade el **contorno** (casco invertido, modificador `ST Outline`): la máscara sale de la alpha de los vertex colors `COL0` del juego (sin contorno en cara y ojos) y el color es la textura base oscurecida. Grosor ajustable en el panel N. |
| **Controles de iluminación** | Los crea el shading junto al personaje y, al generar el rig, pasan a ser parte de él (colección de huesos *Iluminacion*), así que se animan en la misma acción que el personaje. **Ruedas HSV** *Luz* (lado iluminado) y *Ambiente* (sombra): la posición del selector da tono y saturación, y la barra, el valor. **Sol** (`ST Sol`): la luz llega desde donde esté este control hacia la cabeza, y mueve las sombras del cuerpo y de la cara. Todo sigue al hueso `root`. |
| **Rig + Física** | Genera un rig Rigify con el rigger NTE de Gacha Setup (comparte el esqueleto `Bip001-` de Strinova) y aplica la física por constraints. |
| **Física por Constraints** | Aplica (o rehace) solo la física en un rig ya generado. Sliders *Inercia pelo* (0.56), *Inercia flequillo* (0.28), *Inercia ropa* (0.32) e *Inercia pecho* (0.2): un 20% más duros que los de Gacha Setup. El flequillo y los mechones delanteros (los que terminan delante de los ojos) se mueven la mitad que el pelo de atrás. |

La física usa el método de Gacha Setup: cada hueso de pelo, ropa y pecho (`chest_l/r`) tiene un *Damped Track* hacia su propio hijo. Es un ciclo de dependencia a propósito: Blender lo resuelve con la evaluación anterior, así que al animar las cadenas se quedan atrás del cuerpo y se ven con inercia. A diferencia del botón de Gacha, solo toca esos huesos (no los del IK), y antes reorienta cada hueso hacia su hijo para que la pose de reposo no cambie. **Limitación:** el resultado depende de los fotogramas evaluados antes; reproducir de corrido no da lo mismo que saltar a un fotograma, y un render de fotogramas sueltos puede diferir del viewport.

## Estructura del código

Cada área vive en su propio módulo, para que un cambio en una no rompa otra:

| Módulo | Qué contiene |
|---|---|
| `strinova_toon/importer.py` | Importar `.uemodel` / `.fbx` y detectar la carpeta de FModel. Llama al shading y al rig por sus botones, sin importar su código |
| `strinova_toon/rig.py` | Rig con el rigger NTE de Gacha Setup, arreglos sobre él (B-Bones, dedos, pecho) y física de pelo, ropa y pecho |
| `strinova_toon/shading.py` | Materiales toon, sol y empties de la cabeza, panel de iluminación y contorno |
| `strinova_toon/common.py` | Utilidades que usan los tres (`target_mesh`) |
| `strinova_toon/__init__.py` | Datos del add-on, panel N y registro |

El rig depende del shading en un único punto: `shading.lighting_panel_aside()`, que aparta el panel de iluminación mientras corre el rigger de Gacha y después lo une al rig.

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

## Modelos con expresiones

Cada skin trae dos modelos 3D: el de partida (`Mesh3D`) y el de lobby (`Mesh3DLobby`). Casi siempre solo el de lobby trae las expresiones faciales (shape keys); con él, Gacha Setup genera los sliders de la cara.

Si importas un `.fbx` guardado fuera de la exportación de FModel, el add-on reconoce el personaje por el nombre de una de sus carpetas (`.../<Personaje>/<Skin>/...`) y usa sus texturas y materiales de la exportación de FModel. Para eso, la carpeta del panel tiene que apuntar a cualquier personaje dentro de esa exportación.

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
