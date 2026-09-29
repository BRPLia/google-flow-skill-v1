---
name: google-flow
version: 2.0.0
description: Controla Google Flow desde un agente de IA con terminal y Chrome local. Genera y descarga imágenes o videos individuales y por lotes sin copiar prompts manualmente.
---

# Google Flow Skill v2

Esta skill permite que un **agente externo** (Claude Code, Codex, OpenCode u otro con terminal local) convierta una petición en trabajos de Google Flow, los ejecute en Chrome y entregue los archivos descargados. `flow.py` es la única entrada pública. No escribas Playwright ad hoc.

## Requisitos de entorno

- Python 3.10+, Google Chrome y una sesión interactiva de escritorio en la **misma máquina** donde corre el agente.
- Un entorno remoto o sandbox puede ejecutar el script sin mostrar la ventana al usuario. `FLOW_HEADLESS=false` no crea una pantalla visible donde no existe.
- La sesión queda en `session/flowbot-profile/`. Nunca compartas, subas ni copies esa carpeta.
- La skill no necesita una API key. Las generaciones **consumen créditos de Google Flow** según modelo y duración. Comprueba el costo actual en la interfaz o en la [ayuda oficial](https://support.google.com/flow/answer/16526234?hl=es-419).

Lee este archivo completo antes de instalar o ejecutar. Respeta las reglas de terminal y aprobación del workspace anfitrión.

## Arranque

Desde la raíz de esta carpeta:

```powershell
python setup.py
python flow.py status
python flow.py login
```

`setup.py` instala dependencias; ejecútalo cuando prepares el entorno o falte un paquete. `status` comprueba que existe un perfil local, **no** garantiza que Google siga autenticado. `login` abre Chrome visible para que el humano inicie sesión; el agente no debe pedir ni guardar contraseñas. Si un sandbox impide ver la ventana, ejecuta el agente en un terminal de escritorio local.

## Elegir operación

| Petición | Acción del agente |
|---|---|
| Una imagen desde texto | `python flow.py image --prompt "..." --name nombre` |
| Imagen con referencia local | `python flow.py image --prompt "..." --image referencia.png --name nombre` |
| Un video desde texto | `python flow.py video --prompt "..." --name nombre` |
| Animar un fotograma | `python flow.py video --prompt "..." --start inicio.png --name nombre` |
| Interpolar inicio y fin | `python flow.py video --prompt "..." --start inicio.png --end fin.png --name nombre` |
| Dos o más entregables | Construye un JSON y ejecuta `python flow.py batch archivo.json` |

Opciones: `--ratio` (por defecto `9:16`), `--model`, `--out`, `--name`; video admite `--duration 8s` si el modelo ofrece esa duración. Modelos reconocidos por el proveedor actual: imagen `Nano Banana 2 Lite`, `Nano Banana 2`, `Nano Banana Pro`, `Imagen 4`; video `Veo 3.1 - Lite`, `Veo 3.1 - Fast`, `Veo 3.1 - Quality`, `Omni 1.1 Flash`. La disponibilidad real depende de Flow y de la cuenta.

Cada trabajo descarga **un archivo**. Para varias variantes o imágenes por lotes, crea varios `jobs` con nombres distintos y `count: 1`; `count > 1` se rechaza para evitar perder resultados.

## Lotes: el agente se encarga de todo

Interpreta la petición libre del usuario, separa entregables, escribe prompts completos y crea un JSON. No pidas al usuario copiar cada prompt ni esperar y descargar cada resultado. Usa `examples/lote_imagenes.json` para imágenes y `examples/guion_ejemplo.json` para imagen → video.

```json
{
  "project": "mi_lote",
  "defaults": {"ratio": "9:16", "image_model": "Nano Banana 2 Lite", "video_model": "Veo 3.1 - Lite"},
  "jobs": [
    {"type": "image", "name": "imagen_01", "prompt": "A complete, self-contained prompt"},
    {"type": "image", "name": "imagen_02", "prompt": "A different complete prompt"},
    {"type": "video", "name": "clip_01", "start": "imagen_01", "duration": "8s", "prompt": "Motion and action"}
  ]
}
```

Los trabajos se ejecutan **en orden dentro de un proyecto Flow**. `start` puede ser el `name` de una imagen anterior del lote. También admite `image` para una referencia en un trabajo de imagen y `end` para fotograma final de video. `duration` puede ponerse en cada video o como `defaults.video_duration`.

Ejecuta `python flow.py batch mi_lote.json`. Revisa `outputs/<project>/batch_report.json` y comprueba que los archivos indicados existen. Un error en un trabajo no impide que el lote pruebe los siguientes; informa qué entregables fallaron. Los comandos individuales guardan en `outputs/`.

## Cómo actuar ante peticiones comunes

- **"¿Imágenes por lotes?"** Sí: un `job image` por imagen. El agente redacta y ejecuta el JSON, luego entrega las rutas.
- **"¿Contenido para YouTube?"** Sí: esta skill genera imágenes y clips para Shorts o videos largos. El montaje, voz, subtítulos y exportación del video final necesitan un editor o un pipeline adicional.
- **"¿Flow + Remotion + Claude?"** Claude puede usar esta CLI para crear assets y después usar Remotion en otro proyecto para componerlos. Esta carpeta no instala ni ejecuta Remotion.
- **"No aparece Chrome"** Comprueba que el proceso corre en la máquina con escritorio, que Chrome está instalado y que el agente tiene acceso a esa sesión gráfica. Algunos ejecutores, incluido Antigravity en modo sandbox, aíslan el navegador; cambia a ejecución local si quieres verlo.
- **"Quiero personajes consistentes, audio nativo y un short final"** La CLI pública cubre trabajos de Flow. Un pipeline como `short-generator` puede añadir referencias de personajes, ASR y Remotion, pero es otro proyecto y no viene en esta skill.

## Límites y mantenimiento

La automatización usa la interfaz web de Flow; cambios en esa interfaz pueden exigir ajustes de selectores. El agente integrado de Flow también genera medios y lotes; esta skill sirve para dirigir Flow desde un agente externo y guardar archivos locales. No presentes la generación como ilimitada o completamente gratuita.

⚠️ **ADVERTENCIA:** `python flow.py clean nombre_proyecto` borra ese proyecto local de `outputs/`; `python flow.py clean` borra todos los resultados. No ejecutes limpieza sin una solicitud explícita y un objetivo verificado.
