# AGENTS.md — Google Flow Skill v2

Tu tarea en esta carpeta es manejar Google Flow desde la CLI `flow.py`. Lee `SKILL.md` antes de actuar. Para uso normal, trata `flow_provider/` como motor interno y evita escribir Playwright ad hoc.

1. Comprueba que ejecutas en la máquina del usuario con Chrome y escritorio accesible. Un sandbox puede ocultar la ventana, incluso con `FLOW_HEADLESS=false`.
2. Respeta las reglas de terminal del workspace. Ejecuta `python setup.py` si faltan dependencias; `python flow.py status` comprueba el perfil local; `python flow.py login` permite que el humano inicie sesión. Nunca solicites contraseñas.
3. Traduce la petición a uno o más trabajos. Para dos o más imágenes o videos, crea un JSON como `examples/lote_imagenes.json` y ejecuta `python flow.py batch archivo.json`.
4. Cada trabajo descarga un archivo; usa nombres únicos y `count: 1`. Revisa `outputs/<project>/batch_report.json` y confirma que los archivos existen antes de informar éxito.
5. Para contenido de YouTube, explica que esta CLI produce imágenes y clips. Remotion, voz, subtítulos y montaje final requieren otro proyecto.
6. No compartas ni subas `session/`. No limpies `outputs/` sin una petición explícita.

Modelos disponibles en el proveedor actual: imagen `Nano Banana 2 Lite`, `Nano Banana 2`, `Nano Banana Pro`, `Imagen 4`; video `Veo 3.1 - Lite`, `Veo 3.1 - Fast`, `Veo 3.1 - Quality`, `Omni 1.1 Flash`. La disponibilidad depende de Flow y de la cuenta. Los medios consumen créditos.
