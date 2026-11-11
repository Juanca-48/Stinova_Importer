# Stinova_Importer

Add-on de Blender para importar personajes de **Strinova** exportados con FModel y dejarlos listos: toon shading, rig con controles y física por constraints en pelo y ropa.

Probado en Blender 5.2: importación y shading con las 91 skins exportadas de Kanami, Chiyo, Aika (Eika), Flavia y Nora; rig con Kanami, Michele y Aika.

## Qué hace

Panel **Strinova** en el viewport 3D (tecla N):

| Elemento | Qué hace |
|---|---|
| **Importar personaje** | Importa un `.uemodel` (UEFormat) o `.fbx`. También acepta la **carpeta de una skin** (entra en ella sin elegir archivo y pulsa Importar): toma su modelo 3D, el de lobby si lo hay, porque trae las expresiones, y su versión de papel, y los importa juntos. Detecta la carpeta del personaje y, en el mismo paso, aplica el shading y genera el rig (casillas *Aplicar Toon Shading* y *Generar rig* debajo del botón; *Incluir versión de papel* trae también la versión de papel de la skin). Todo lo que crea queda en una colección `<Personaje> <Skin>` (por ejemplo `Flavia S001`). |
| **Carpeta del personaje** | Carpeta de la exportación de FModel con las texturas y los JSON de materiales. Se rellena sola al importar desde FModel; solo hace falta para un `.fbx` guardado en otro sitio. |
| Shading | Reconstruye los materiales a partir de los JSON y PNG de FModel (toon con luz del sol, cara con SDF, normal map, matcap). Crea el sol del personaje (`ST_Light <malla>`) y los empties de su cabeza. Añade el **contorno** (casco invertido, modificador `ST Outline`): la máscara sale de la alpha de los vertex colors `COL0` del juego (sin contorno en cara y ojos) y el color es la textura base oscurecida. Grosor ajustable en el panel N. |
| **Controles de iluminación** | Los crea el shading junto al personaje y, al generar el rig, pasan a ser parte de él (colección de huesos *Iluminacion*), así que se animan en la misma acción que el personaje. **Ruedas HSV** *Luz* (lado iluminado) y *Ambiente* (sombra): la posición del selector da tono y saturación, y la barra, el valor. **Sol** (`ST Sol`): la luz llega desde donde esté este control hacia la cabeza, y mueve las sombras del cuerpo y de la cara. Todo sigue al hueso `root`. |
| Rig | Genera un rig Rigify con el rigger NTE de Gacha Setup (comparte el esqueleto `Bip001-` de Strinova), con los controles de iluminación y la física de pelo, ropa y pecho. |
| **Física** (casilla) | Activa o desactiva la física al instante, sin rehacer el rig; se puede animar. Sliders *Inercia pelo* (0.56), *Inercia flequillo* (0.28), *Inercia ropa* (0.32) e *Inercia pecho* (0.2): un 20% más duros que los de Gacha Setup. El flequillo y los mechones delanteros (los que terminan delante de los ojos) se mueven la mitad que el pelo de atrás. |

La física usa el método de Gacha Setup: cada hueso de pelo, ropa y pecho (`chest_l/r`) tiene un *Damped Track* hacia su propio hijo. Es un ciclo de dependencia a propósito: Blender lo resuelve con la evaluación anterior, así que al animar las cadenas se quedan atrás del cuerpo y se ven con inercia. A diferencia del botón de Gacha, solo toca esos huesos (no los del IK), y antes reorienta cada hueso hacia su hijo para que la pose de reposo no cambie. **Limitación:** el resultado depende de los fotogramas evaluados antes; reproducir de corrido no da lo mismo que saltar a un fotograma, y un render de fotogramas sueltos puede diferir del viewport.

## Versión de papel

Cada skin trae también su versión de papel (carpeta `Mesh2D` de la skin; el nombre varía: `_PPM_`, `_PMM_`, `_skin`): una lámina con el personaje pintado. Con la casilla **Incluir versión de papel** del panel, al importar el modelo 3D se importa también la de su skin (la busca en `Mesh2D` junto a la carpeta del modelo 3D, también en un árbol de FBX como el de FModel, y si no, en la exportación de FModel); sin ella, solo el 3D. También se puede importar después: si importas la de un personaje que ya está en la escena con rig, se une a él: queda en su colección, la mueve el mismo rig (sus huesos son los del modelo 3D) y usa su misma iluminación.

El botón **Versión de papel** del panel (propiedad `st_paper` del rig) cambia entre el modelo 3D y el de papel en un solo fotograma, como en el juego. Se puede animar: con un keyframe en cada estado el cambio es instantáneo. El juego lo disimula con la animación (un giro, abrir los brazos), así que conviene hacer el cambio en mitad de un movimiento.

Sin su personaje 3D en la escena, la versión de papel se importa sola y sin rig.

## Accesorios (máscaras, sombreros)

Para mover un accesorio por separado o quitarlo de escena. Cada accesorio tiene además un interruptor **Mostrar <accesorio>** en el panel (propiedad `st_show_<hueso>` del rig, animable) que lo oculta en viewport y render, con su contorno. Cada uno tiene un hueso en la colección **Accesorios** (una máscara pequeña, triángulo invertido con dos círculos, delante de la pieza). Es hijo de la cabeza: sigue al personaje, pero se puede mover, girar o escalar a 0 para quitarlo, y se anima como cualquier hueso.

- **Con hueso propio** (`mask_bone`, `maskA_L/R_bone`... en Fragrans, Kanami S211–S215, MoBai S206–S210): el control se crea solo al importar.
- **Máscaras de Eika** (S001, S101, S103, S106, S107...): cuelgan de sus huesos `hair_tt_*` (*tou tao*, cubrecabeza). Al importar se crea `ACC-Mascara`, padre de esos huesos e hijo de la cabeza; los pesos no cambian. En S111 la máscara ya tiene `mask_bone`.
- **Sin hueso propio** (la mayoría de sombreros, y máscaras como la de Aika S001, que cuelga de un hueso de pelo y se movía con su física): selecciona la malla, entra en Edit Mode, selecciona la pieza (L sobre ella) y pulsa **Crear hueso de accesorio** en el panel. La pieza pasa a moverse solo con su hueso (`ACC-<nombre>`), que cuelga del hueso del cuerpo que la movía (la cabeza).

## Varios personajes en una escena

Cada personaje tiene su propio sol (`ST_Light <malla>`), sus empties de la cabeza y su panel de iluminación: dos personajes se pueden sombrear distinto (uno en interior y otro en exterior). Los sliders de física son propiedades de cada rig: el panel N muestra los del personaje seleccionado, y también están en *Object Properties > Custom Properties* del rig.

Al generar el rig, el add-on aparta de la escena a los demás personajes mientras corre Gacha Setup (su rigger trabaja sobre toda la escena) y protege los controles de cara ya creados, que Gacha borra por nombre al hacer una cara nueva.

## Estructura del código

Cada área vive en su propio módulo, para que un cambio en una no rompa otra:

| Módulo | Qué contiene |
|---|---|
| `strinova_toon/importer.py` | Importar `.uemodel` / `.fbx` y detectar la carpeta de FModel. Llama al shading y al rig por sus botones, sin importar su código |
| `strinova_toon/rig.py` | Rig con el rigger NTE de Gacha Setup, arreglos sobre él (B-Bones, dedos, pecho) y física de pelo, ropa y pecho |
| `strinova_toon/paper.py` | Versión de papel unida al rig del 3D y el cambio entre las dos |
| `strinova_toon/accessory.py` | Huesos de accesorios (máscaras, sombreros) y su botón |
| `strinova_toon/face.py` | Control de mirada y secciones de los sliders de la cara |
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

Casi todos los esqueletos de Strinova no traen deformadores de cara (solo los globos oculares, y en algunos personajes las pestañas): toda la expresión está en los shape keys. Al generar el rig, el add-on reordena los sliders de Gacha en secciones con título, cada una con su colección de huesos dentro de *Face*: **Ojos**, **Pupilas**, **Cejas** a la izquierda de la cara y **Boca**, **Labios**, **Cabeza y otros** a la derecha. Boca y Labios se separan midiendo la geometría al generar el rig: en *Boca* van los fonemas y los shape keys que abren la boca (separan los labios más de 4 mm), y en *Labios* los que la mueven sin abrirla (sonrisas, comisuras, dientes, lengua). Se clasifican por el nombre del shape key con una tabla de raíces en pinyin e inglés traducidas (*yan* ojo, *mei* ceja, *zui* boca, *tongkong* pupila, *sanjiao* boca triangular, *gulian* mejillas infladas...), en `SECTIONS` de `face.py`. Se armó con los 390 nombres de los 506 modelos de lobby y se comprobó midiendo qué zona de la cara mueve cada uno.

**Huesos faciales**: algunos modelos sí traen deformadores de cara (`*_SkinJNT`): el rig facial completo de Fragrans, Yugiri y Mara (lobby: párpados, cejas, labios, mandíbula, mejillas, nariz, ojos, dientes y lengua) y los párpados del modelo de partida de Chiyo. Si el modelo los tiene, el rig los muestra como controles en la colección *Cara: Huesos* (un círculo delante de cada uno, color por lado) y los dientes y la lengua en *Cara: Boca interior* (oculta al importar). Se animan rotándolos o moviéndolos, junto con los sliders de shape keys. Los demás personajes no cambian.

**Seguidor de cabeza**: el rig sale con el `head-controller` de Gacha activo (la cabeza apunta a ese control delante de la cara). Se apaga con *Use Head Controller* en el engranaje sobre la cabeza (`plate-settings`).

**Mirada**: en los personajes con globos oculares (`eye_l/r_ball_01`) se añade el control *Mirada* delante de la cara, que sigue a la cabeza, con un objetivo por ojo (*Mirada.L/R*) para ajustar cada ojo por separado.

Si importas un `.fbx` guardado fuera de la exportación de FModel, el add-on reconoce el personaje por el nombre de una de sus carpetas (`.../<Personaje>/<Skin>/Mesh3D/...`; la carpeta de la skin puede ser `S001` o el nombre de la skin, como `Kanami/Ruiseñor/`, y da nombre a la colección) y usa sus texturas y materiales de la exportación de FModel. Para eso, la carpeta del panel tiene que apuntar a cualquier personaje dentro de esa exportación.

## Prueba

```
blender -b --python tests/smoke_test.py -- "D:\...\Characters\Kanami\S215\Mesh3D\SK_Kanami_Mesh_S215.uemodel"
```

Termina con `[smoke] OK`, o con código de salida 1 si algo falla. Con dos personajes en la misma escena:

```
blender -b --python tests/two_characters_test.py -- "<personaje 1>" "<personaje 2>"
```

Versión de papel y cambio 3D / papel:

```
blender -b --python tests/paper_switch_test.py -- "<modelo 3D>" "<modelo Mesh2D>"
blender -b --python tests/paper_switch_test.py -- "<modelo 3D>" -    # los dos en una sola importación
```

## Limitaciones conocidas

- **Sombra plana**: el color de sombra es un tinte fijo, no el atlas de rampas del juego (`RampID`). `Mask1` y `Mask2` todavía no se usan.
- **Hueso de la cabeza fijo**: se busca como `Bip001-Head` o `DEF-spine.006`.
- **FBX de otras herramientas sin probar**: un FBX de Unreal Editor o de otros conversores puede traer escala en cm o los ejes de los huesos cambiados. Los FBX exportados desde Blender funcionan.
- **Huesos sin reacción**: la inercia no reacciona al mover el `root` ni al levantar las piernas (la falda cuelga de la cadera).
