# Strinova Toon Setup

Add-on de Blender que importa personajes de **Strinova** y los deja listos para animar y renderizar con un solo botón.

Funciona con los dos formatos de modelo: **`.uemodel`** y **`.fbx`**, vengan de donde vengan.

## Qué hace

- **Importa** `.uemodel` y `.fbx`, o la carpeta entera de una skin: trae el modelo 3D y su versión de papel juntos.
- **Toon shading** como en el juego: materiales reconstruidos desde las texturas, sombra de cara suave y contorno.
- **Iluminación por personaje**: un sol que se mueve con un control y dos ruedas de color (luz y sombra) dentro del rig, todo animable.
- **Rig completo** con [Gacha Setup](https://github.com/PaoloESAN/gacha-setup) y física de pelo, ropa y pecho que se activa con una casilla.
- **Cara ordenada**: los controles de expresión agrupados en Ojos, Pupilas, Cejas, Boca, Labios y Cabeza, con colores, control de mirada y parpadeo.
- **Versión de papel**: cambia entre el modelo 3D y el de papel en un fotograma, como en el juego.
- **Accesorios**: máscaras y sombreros con su propio hueso y un interruptor para mostrarlos u ocultarlos.
- **Varios personajes** en la misma escena, cada uno con su propia luz.
- **Armas** con su propio botón: cuerpo, mira, colgante y cargador montados, con su shading, y un botón para ponerlas en la mano del personaje.

## Necesitas

| | |
|---|---|
| **Blender 5.2** | |
| **[Gacha Setup](https://github.com/PaoloESAN/gacha-setup/releases)** | Obligatorio para el rig: este add-on usa su rigger. |
| **[UEFormat](https://github.com/h4lfheart/UEFormat)** | Solo para importar `.uemodel` (con `.fbx` no hace falta). |

## Descarga e instalación

1. Instala **[Gacha Setup](https://github.com/PaoloESAN/gacha-setup/releases)** y, si vas a usar `.uemodel`, **[UEFormat](https://github.com/h4lfheart/UEFormat)**, siguiendo las instrucciones de cada uno.
2. Descarga `strinova_toon-vX.Y.Z.zip` de la última versión en **[Releases](https://github.com/Juanca-48/Stinova_Importer/releases/latest)**. No lo descomprimas.
3. En Blender: *Edit > Preferences > Add-ons > Install from Disk* y elige ese zip.
4. Activa **Strinova Toon Setup** y comprueba que **Gacha Setup** y **Rigify** (incluido en Blender) también estén activos.

Para actualizar, instala el zip de la versión nueva de la misma forma y reinicia Blender.

El panel aparece en el viewport 3D, pestaña **Strinova** (tecla N).

La guía de uso completa, con todas las opciones, está en [INSTRUCCIONES.txt](INSTRUCCIONES.txt).

## Licencia

[GPL-3.0-or-later](LICENSE), la misma que Blender y que [Gacha Setup](https://github.com/PaoloESAN/gacha-setup), cuyo rigger usa este add-on para generar el rig.
