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
- **Armas** y objetos de los personajes, con su propio botón de importación.

## Necesitas

| | |
|---|---|
| **Blender 5.2** | |
| **[Gacha Setup](https://github.com/PaoloESAN/gacha-setup/releases)** | Obligatorio para el rig: este add-on usa su rigger. |
| **[UEFormat](https://github.com/h4lfheart/UEFormat)** | Solo para importar `.uemodel` (con `.fbx` no hace falta). |

## Descarga e instalación

1. Descarga el repositorio: botón verde **Code > Download ZIP**, y descomprímelo.
2. Dentro está la carpeta `strinova_toon`. Comprímela sola en un zip (en Windows: clic derecho > *Enviar a > Carpeta comprimida*).
3. En Blender: *Edit > Preferences > Add-ons > Install from Disk* y elige ese zip.
4. Activa **Strinova Toon Setup** (y Gacha Setup, si no lo estaba).

El panel aparece en el viewport 3D, pestaña **Strinova** (tecla N).

La guía de uso completa, con todas las opciones, está en [INSTRUCCIONES.txt](INSTRUCCIONES.txt).
