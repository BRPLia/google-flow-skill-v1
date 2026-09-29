# Google Flow Skill v2

Dile a un agente con terminal local: **“Crea tres imágenes y dos clips sobre esta idea; usa Google Flow y entrégame los archivos.”** El agente prepara los prompts, controla Flow en Chrome, espera la generación y descarga los resultados. También puede ejecutar lotes a partir de un JSON.

Funciona con Claude Code, Codex, OpenCode u otros agentes **cuando se ejecutan en tu equipo con escritorio y Chrome visible**. El requisito es el entorno local, no la marca del agente.

## Qué incluye

- Imagen desde texto o con referencia local.
- Video desde texto, fotograma inicial o fotogramas inicial y final.
- Lotes ordenados de imágenes y videos, con encadenamiento imagen → video.
- Selección de modelo, formato y duración de video compatible con Flow.
- Descarga automática a `outputs/` y reporte `batch_report.json`.

Cada trabajo guarda un resultado. Para diez imágenes, crea diez trabajos `image`; consulta [el ejemplo de lote](examples/lote_imagenes.json). La skill pública entrega **assets de Flow**. Para un Short terminado con montaje, voz y subtítulos, conecta después un editor como Remotion o un pipeline aparte.

## Instalación

Necesitas Python 3.10+ y Google Chrome. Abre un agente en esta carpeta, haz que lea `SKILL.md` y pídele instalarla. Los comandos son:

```powershell
python setup.py
python flow.py status
python flow.py login
```

`login` abre Chrome para que **tú** inicies sesión. El perfil queda en `session/flowbot-profile/`; nunca lo subas al repositorio ni lo compartas. `status` solo detecta el perfil, no prueba que la sesión siga autenticada. Si las reglas de tu workspace exigen mostrar o aprobar comandos, el agente debe respetarlas.

Repositorio actual: [BRPLia/google-flow-skill-v1](https://github.com/BRPLia/google-flow-skill-v1). El nombre de la URL conserva “v1”; este código corresponde a la v2.

## Uso rápido

```powershell
python flow.py image --prompt "Three distinct paper flowers on a plain table, vertical 9:16" --name flores
python flow.py video --prompt "A gentle breeze moves the paper flowers" --start outputs/flores.png --model "Veo 3.1 - Lite" --duration 8s --name flores_clip
python flow.py batch examples/lote_imagenes.json
```

Para lotes, el agente debe escribir el JSON y ejecutar `batch`; tú no tienes que copiar prompts uno por uno. Los resultados quedan en `outputs/<project>/`. Revisa el reporte del lote para ver éxitos y errores.

## Preguntas frecuentes

**¿Crea imágenes por lotes?** Sí. Cada entrada `image` del JSON genera y descarga una imagen. Puedes mezclar imágenes y videos en el mismo lote.

**¿Sirve para contenido de YouTube?** Sí, para crear las imágenes y los clips. Un video completo también requiere guion, voz si corresponde, edición y exportación. Esta skill no hace ese montaje por sí sola.

**¿Cómo conecto Flow con Remotion y Claude?** Claude dirige `flow.py batch` y recibe rutas de MP4/PNG. Un proyecto Remotion usa esos archivos locales como fuentes y renderiza el video final. Remotion se instala y configura por separado; esta skill no lo incluye.

**¿Por qué no aparece la ventana de Chrome en Antigravity?** Si el código corre en un sandbox remoto, la ventana puede abrirse allí y no en tu escritorio. Usa un ejecutor local con acceso a la pantalla. Claude Code, Codex u OpenCode también necesitan ejecución local para mostrarla; el nombre del agente no garantiza visibilidad.

**¿Es gratis?** La automatización no añade una suscripción propia. Google Flow usa créditos para generar medios; puede haber créditos diarios sin suscripción y el costo depende del modelo. Comprueba los [límites y costos actuales](https://support.google.com/flow/answer/16526234?hl=es-419).

## Archivos

- `flow.py`: CLI pública.
- `SKILL.md`: instrucciones para el agente.
- `flow_provider/`: automatización interna de Flow.
- `examples/`: lotes de ejemplo.
- `session/`: perfil privado de Chrome, excluido de Git.
- `outputs/`: descargas locales, excluidas de Git.

La automatización depende de la interfaz web de Flow y puede requerir mantenimiento cuando Google la cambie.
