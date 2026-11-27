# SPDX-License-Identifier: GPL-3.0-or-later
"""Spanish UI. The add-on's text is in English; with Blender in Spanish (Preferences > Interface >
Translation) labels, tooltips and reports show these. A new UI string needs its line here."""

ES = {
    # panel
    "Root folder:": "Carpeta raíz:",
    "Root folder": "Carpeta raíz",
    "Folder with the character's textures and material JSONs (FModel's Characters\\<Name>). "
    "Filled on import from the model's path":
        "Carpeta con las texturas y los JSON de materiales del personaje (Characters\\<Nombre> de FModel). "
        "Se rellena al importar a partir de la ruta del modelo",
    "Weapons": "Armas",
    "In the hand of {}": "En la mano de {}",
    "Right hand (trigger)": "Mano derecha (gatillo)",
    "Left hand (grip)": "Mano izquierda (agarre)",
    "Outline width": "Grosor contorno",
    "Outline in viewport": "Contorno en el viewport",
    "Fast viewport": "Viewport rápido",
    "For animating: shows flat textures, without lighting, outline or effects, in the 3D views only. Nothing is lost (colours, lights, keyframes) and renders don't change":
        "Para animar: muestra las texturas planas, sin iluminación, contorno ni efectos, solo en las vistas 3D. No se pierde nada (colores, luces, keyframes) y los renders no cambian",
    "Lighting": "Iluminación",
    "Lighting Type:": "Tipo de iluminación:",
    "Rig Panel": "Panel del rig",
    "Parameter Panel": "Panel de parámetros",
    "Colours and intensities from the wheels next to the character":
        "Colores e intensidades de las ruedas junto al personaje",
    "Colours from this panel; the rig's wheels are hidden": "Colores de este panel; las ruedas del rig se ocultan",
    "Custom Colors": "Colores personalizados",
    "Ambient": "Ambiente",
    "Sharp Lit": "Luz dura",
    "Soft Lit": "Luz suave",
    "Sharp Shadow": "Sombra dura",
    "Soft Shadow": "Sombra suave",
    "Rim Lit": "Borde iluminado",
    "Rim Shadow": "Borde en sombra",
    "Rim Scale": "Intensidad del borde",
    "Extra Rim": "Borde extra",
    "Shadow Softness": "Suavidad de la sombra",
    "Hair Shadow": "Sombra del pelo",
    "Shadow the hair casts on the face": "Sombra que el pelo hace en la cara",
    "Strength of the rim light": "Fuerza de la luz de borde",
    "Rim light for every material, also those whose game data has none":
        "Luz de borde para todos los materiales, también los que no la traen en los datos del juego",
    "Edge between light and shadow: 0 hard, higher softer (1 = default)":
        "Borde entre luz y sombra: 0 duro, más alto más suave (1 = por defecto)",
    "Paper version": "Versión de papel",
    "Mask": "máscara",
    "Show {}": "Mostrar {}",
    "Physics": "Física",
    "Select the mesh or its armature": "Selecciona la malla o su armature",
    "Apply Toon Shading": "Aplicar Toon Shading",
    "Toon materials, lighting and outline on import": "Materiales toon, iluminación y contorno al importar",
    "Generate rig": "Generar rig",
    "Rig with Gacha Setup, face, gaze and physics on import": "Rig con Gacha Setup, cara, mirada y física al importar",
    "Include paper version": "Incluir versión de papel",
    "IK method": "Método de IK",
    "How the generated rig's arm and leg IK aims the elbows and knees":
        "Cómo apunta el IK de brazos y piernas del rig los codos y las rodillas",
    "Rotation": "Rotación",
    "Elbows and knees swing by rotating the arm and leg IK controls (upper_arm_ik, thigh_ik). "
    "Their poles are ready but off: Rigify's Pole switch turns them on":
        "Codos y rodillas giran rotando los controles IK de brazo y pierna (upper_arm_ik, thigh_ik). "
        "Sus poles quedan preparados pero apagados: el interruptor Pole de Rigify los enciende",
    "Poles": "Poles",
    "Elbows and knees aim at pole targets, 60 cm away, shown in the IK Poles bone "
    "collection; the arm and leg IK controls' rotation does nothing then, so they are hidden":
        "Codos y rodillas apuntan a objetivos de pole, a 60 cm, visibles en la colección de huesos IK Poles; "
        "la rotación de los controles IK de brazo y pierna no hace nada entonces, así que se ocultan",
    "Also imports the skin's paper version (Mesh2D), joined to the 3D rig with its switch":
        "Importa también la versión de papel (Mesh2D) de la skin, unida al rig del 3D con su interruptor",
    # character import
    "Import character": "Importar personaje",
    "Imports a character .uemodel (UEFormat) or .fbx and optionally applies shading and rig. "
    "With a skin folder (no file picked) it imports its 3D model and its paper version":
        "Importa un .uemodel (UEFormat) o .fbx del personaje y opcionalmente aplica shading y rig. "
        "Con una carpeta de skin (sin elegir archivo) importa su modelo 3D y su versión de papel",
    "Not found: {}": "No existe: {}",
    "The folder has no Mesh3D or Mesh2D with an .fbx or .uemodel": "La carpeta no tiene Mesh3D ni Mesh2D con un .fbx o .uemodel",
    "UEFormat is not enabled: enable it or import the character as .fbx":
        "UEFormat no está activo: actívalo o importa el personaje como .fbx",
    "Unsupported format, use .uemodel or .fbx": "Formato no soportado, usa .uemodel o .fbx",
    "{}: this skin has no paper version (Mesh2D)": "{}: esta skin no trae versión de papel (Mesh2D)",
    "The file has no mesh with a skeleton": "El archivo no trae una malla con esqueleto",
    "imported": "importado",
    "paper on {}": "papel en {}",
    " | failed: {} (see console)": " | falló: {} (ver consola)",
    # shading
    "Creates the node groups and the light/head rig, and rebuilds the character's materials":
        "Crea los node groups, el rig de luz/cabeza y reconstruye los materiales del personaje",
    "Folder not found: {}": "Carpeta no encontrada: {}",
    "{} has no armature": "{} no tiene armature",
    "Bone not found: {}": "No se encontró el hueso {}",
    "{}/{} materials set up (details in the console)": "{}/{} materiales configurados (detalle en la consola)",
    "{} of {} materials without textures (e.g. {}): not found in {}. Check the Root folder":
        "{} de {} materiales sin texturas (p. ej. {}): no están en {}. Revisa la Carpeta raíz",
    " | {} materials without textures: check the Root folder ({})":
        " | {} materiales sin texturas: revisa la Carpeta raíz ({})",
    " | {} materials without the game's shared matcaps: set the FModel export folder in the preferences and import again":
        " | {} materiales sin los MatCap compartidos del juego: pon la carpeta de exportación de FModel en las preferencias y vuelve a importar",
    " | {} animated effects with the add-on's own textures: for the game's, set the FModel export folder in the preferences":
        " | {} efectos animados con texturas propias del add-on: para las del juego, pon la carpeta de exportación de FModel en las preferencias",
    " | {} materials without textures: not found in {}": " | {} materiales sin texturas: no están en {}",
    " | no facial expressions in this model: import the lobby one, {}":
        " | este modelo no trae expresiones faciales: importa el de lobby, {}",
    " | no facial expressions in this model (the lobby model, Mesh3DLobby, usually has them)":
        " | este modelo no trae expresiones faciales (el de lobby, Mesh3DLobby, suele traerlas)",
    # rig
    "Generates the Rigify rig with Gacha Setup (NTE mode), with lighting controls and hair, clothes and chest physics":
        "Genera el rig Rigify con Gacha Setup (modo NTE), con controles de luz y física de pelo, ropa y pecho",
    "Hair inertia": "Inercia pelo",
    "Bangs inertia": "Inercia flequillo",
    "Clothes inertia": "Inercia ropa",
    "Skirt collision": "Colisión de falda",
    "Skirt smoothing": "Suavizado de falda",
    "Chest inertia": "Inercia pecho",
    "{}: how much it lags and drags when animating": "{}: cuánto se retrasa y arrastra al animar",
    "Turns hair, clothes and chest physics on": "Activa la física de pelo, ropa y pecho",
    "Enable the Gacha Setup add-on": "Activa el add-on Gacha Setup",
    "{} is already rigged or is not a Strinova skeleton": "{} ya está riggeado o no es un esqueleto de Strinova",
    "Gacha Setup did not generate the rig (check the console)": "Gacha Setup no generó el rig (revisa la consola)",
    "Rig ready: {}, {} chains with physics": "Rig listo: {}, {} cadenas con física",
    # paper version and accessories
    "Shows the paper version instead of the 3D model": "Muestra la versión de papel en lugar del modelo 3D",
    "Shows or hides {} (animatable)": "Muestra u oculta {} (se puede animar)",
    # weapons
    "Import weapon": "Importar arma",
    "Imports a weapon (.uemodel or .fbx) into its own collection. With the weapon's body or the "
    "skin folder, it also brings its sight and pendant and puts them in place":
        "Importa un arma (.uemodel o .fbx) en su propia colección. Con el cuerpo del arma o la carpeta "
        "de la skin, trae también su mira y su colgante y los coloca en su sitio",
    "Include sight": "Incluir mira",
    "Brings the weapon's sight and puts it in place; without it, only the body":
        "Trae la mira del arma y la coloca en su sitio; sin ella, solo el cuerpo",
    "Pick the weapon (.uemodel or .fbx) or the folder of one of its skins":
        "Elige el arma (.uemodel o .fbx) o la carpeta de una de sus skins",
    "That is a character, not a weapon: use Import character": "Eso es un personaje, no un arma: usa Importar personaje",
    "UEFormat is not enabled: enable it or import the weapon as .fbx": "UEFormat no está activo: actívalo o importa el arma como .fbx",
    "The file has no model": "El archivo no trae ningún modelo",
    ", {}/{} materials": ", {}/{} materiales",
    ", lit by {}": ", con la luz de {}",
    ", no shading: FModel's SkinAssets folder not found (set it in the add-on's preferences)":
        ", sin shading: no encuentro la carpeta SkinAssets de FModel (ponla en las preferencias del add-on)",
    # preferences
    "FModel export folder": "Carpeta de exportación de FModel",
    "FModel's export with the game's textures (the folder holding SkinAssets, or SkinAssets itself). "
    "Filled in by itself the first time you import from it. Used when a model elsewhere (an .fbx, a "
    "weapon) has no textures near it":
        "La exportación de FModel con las texturas del juego (la carpeta que contiene SkinAssets, o SkinAssets). "
        "Se rellena sola la primera vez que importas desde ella. Se usa cuando un modelo guardado en otro sitio "
        "(un .fbx, un arma) no tiene texturas cerca",
    ", with {}": ", con {}",
    " and ": " y ",
    "sight": "mira",
    "pendant": "colgante",
    "magazine": "cargador",
    "{}: {} mesh(es){}, {} controls{}": "{}: {} malla(s){}, {} controles{}",
    "Connect weapon": "Conectar arma",
    "With the weapon selected: click a character in the viewport and the weapon goes to its "
    "right hand (trigger). Esc or right click cancels":
        "Con el arma seleccionada: haz clic en un personaje en el viewport y el arma va a su mano "
        "derecha (gatillo). Esc o clic derecho cancela",
    "{} in the hand of {}": "{} en la mano de {}",
    "Select the weapon and the character (its rig or its mesh) together":
        "Selecciona el arma y el personaje (su rig o su malla) a la vez",
    "Click the character that will hold the weapon  |  Esc / right click: cancel":
        "Haz clic en el personaje que sostendrá el arma  |  Esc / clic derecho: cancelar",
    "No rigged character there: click on its mesh": "Ahí no hay un personaje con rig: haz clic sobre su malla",
    "Disconnect weapon": "Desconectar arma",
    "Releases the weapon from the character's hands: it goes back to where it was before connecting":
        "Suelta el arma de las manos del personaje: vuelve a donde estaba antes de conectarla",
    "{} out of the hand of {}": "{} fuera de la mano de {}",
    "Connect left hand": "Conectar mano izquierda",
    "Puts the character's left hand on the weapon's grip (a green control that slides along "
    "the barrel). The hand control still adjusts how it rests":
        "Pone la mano izquierda del personaje en el agarre del arma (control verde que se desliza a lo "
        "largo del cañón). El control de la mano sigue sirviendo para ajustar cómo la apoya",
    "The weapon follows the character's right hand (trigger)": "El arma sigue la mano derecha del personaje (gatillo)",
    "The character's left hand goes to the weapon's grip": "La mano izquierda del personaje va al agarre del arma",
    "Could not create the grip on this weapon": "No se pudo crear el agarre en esta arma",
    "Left hand of {} on the grip of {}": "Mano izquierda de {} en el agarre de {}",
}

# operator labels are looked up in the "Operator" context, everything else in the default one.
# Blender's own translation wins in those, so a word it already translates otherwise goes in CTX.
CTX = "Strinova"
translations = {"es": {(ctx, en): es for en, es in ES.items() for ctx in ("*", "Operator", CTX)}}
