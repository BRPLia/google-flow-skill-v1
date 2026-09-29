"""
Selección de items del canvas y upload de frames para modo Fotogramas/Ingredientes.
"""
from .browser import get_page
from .registry import capture_name
import re

SEL_ADD_INGREDIENT = (
    'button.add-menu-trigger, '
    'button[aria-haspopup="dialog"]:has-text("Crear"), '
    'button[aria-haspopup="dialog"]:has-text("Añadir"), '
    'button[aria-haspopup="dialog"]:has-text("Agregar"), '
    'button[aria-haspopup="dialog"]:has-text("Add"), '
    'button[aria-haspopup="dialog"][aria-label*="recurso"], '
    'button[aria-haspopup="dialog"][aria-label*="Añadir"], '
    'button[aria-haspopup="dialog"][aria-label*="Crear"]'
)
def _asb_key(src: str) -> str | None:
    """Identificador completo; ignora dominio, query y sufijo de tamaño."""
    from urllib.parse import urlsplit
    path = urlsplit(src or "").path
    if "/asb/" not in path:
        return None
    return path.split("/asb/", 1)[1].split("=", 1)[0] or None


_asset_asb_keys: dict[str, str] = {}


async def _matching_asset_image(scope, uuid: str, key: str | None):
    for img in await scope.locator("img").all():
        media_id = await img.get_attribute("data-media-id")
        src = await img.get_attribute("src") or ""
        if media_id == uuid or (key and _asb_key(src) == key) or re.search(
            r"(?:[?&]name=|/(?:image|video)/)" + re.escape(uuid) + r"(?:[?&#/=]|$)", src
        ):
            return img
    return None


async def select_ingredients_by_name(uuids: list[str]) -> None:
    """Seleccionar por UUID o por ASB completo observado en la tarjeta de ese UUID."""
    page = await get_page()
    for uuid in uuids:
        key = _asset_asb_keys.get(uuid)
        canvas_img = page.locator(f'img[data-media-id="{uuid}"]').first
        if await canvas_img.count():
            key = _asb_key(await canvas_img.get_attribute("src") or "") or key
        panel = page.locator(SEL_PANEL_RECURSOS).first
        if not await panel.is_visible():
            await page.locator(SEL_ADD_INGREDIENT).first.click()
        await panel.wait_for(state="visible", timeout=8_000)
        await _switch_panel_tab(page, re.compile(r"Todos|All", re.I))
        search = panel.locator('input.search-input, input#add-menu-input').first
        if await search.count():
            await search.fill("")
        await page.wait_for_timeout(1_000)
        target = None
        for step in range(12):
            target = await _matching_asset_image(panel, uuid, key)
            if target is not None:
                break
            # Scroll únicamente en la lista del panel; nunca en la página de fondo.
            listing = panel.get_by_role("listbox").first
            if not await listing.count():
                break
            await listing.evaluate("el => { el.scrollTop += Math.max(el.clientHeight * 0.8, 200); }")
            await page.wait_for_timeout(400)
        if target is None:
            from pathlib import Path
            Path("scratch").mkdir(exist_ok=True)
            await page.screenshot(path="scratch/select_ingredient_error.png")
            await page.keyboard.press("Escape")
            raise RuntimeError(f"No se encontró el frame {uuid} en el panel; ASB conocido={bool(key)}")
        await target.click()
        await page.wait_for_timeout(500)
        attached = page.get_by_role("button", name=re.compile(r"^Ingrediente$|^Ingredient$"))
        if await _matching_asset_image(attached, uuid, key) is None:
            if await panel.is_visible():
                add = panel.get_by_role("button", name=re.compile(r"Agregar a la instrucción|Add to prompt|Add to instruction", re.I)).first
                await add.wait_for(state="visible", timeout=5_000)
                await add.click()
        if await panel.is_visible():
            await page.keyboard.press("Escape")
        for attempt in range(20):
            if await _matching_asset_image(attached, uuid, key) is not None:
                print(f"    [ingrediente] Frame adjunto verificado: {uuid}")
                break
            await page.wait_for_timeout(250)
        else:
            raise RuntimeError(f"No se confirmó el frame adjunto {uuid}; generación detenida.")


# ── Voz nativa: pestaña "Voces" del panel de recursos ────────────────────────
# Flow abre el panel siempre en "Todos". Para que el modelo narre con una voz
# concreta (y no con una distinta en cada clip) hay que cambiar a "Voces",
# buscarla por nombre y confirmar con "Seleccionar voz".
SEL_PANEL_RECURSOS = (
    'flow-add-menu-popover-content, '
    'div[role="dialog"]:has(input[placeholder*="Buscar"]), '
    'div[role="dialog"]:has(input[placeholder*="Search"])'
)
# El texto de estos controles lleva pegada la ligadura del ícono Material
# Symbols ("voice_selectionVoces"), así que hay que buscar por SUBCADENA: una
# regex anclada con ^...$ no coincide nunca. Calibrado contra el DOM real.
_VOICES_TAB_RE = re.compile(r"Voces|Voices", re.IGNORECASE)
_ALL_TAB_RE = re.compile(r"Todos|All", re.IGNORECASE)
_PICK_VOICE_RE = re.compile(r"(Seleccionar voz|Select voice)", re.IGNORECASE)

# "Diálogo de ejemplo": el textarea del pane de vista previa. No es decorativo —
# el idioma de esa frase decide el ACENTO con el que la voz narra. En blanco, las
# voces leen el español con acento inglés. Se busca por placeholder y NO con un
# `textarea` a secas: el panel tiene un segundo textarea ("Personalizar el
# rendimiento") y la página arrastra otro oculto sin placeholder.
_SEL_MUESTRA = (
    'textarea[placeholder*="listo para comenzar"], '
    'textarea[placeholder*="ready to get started"]'
)
DEFAULT_VOICE_SAMPLE = "hola a todos"


async def _switch_panel_tab(page, tab_re: re.Pattern) -> bool:
    """Cambia de pestaña dentro del panel de recursos. Devuelve si quedó activa.

    Flow RECUERDA la última pestaña abierta. Eso importa: tras elegir una voz el
    panel se queda en 'Voces', donde no existe el botón de subir archivos. Y
    volver a clickear una pestaña que ya está activa cuelga 30 s porque el
    `<nav role="tablist">` intercepta el puntero.
    """
    panel = page.locator(SEL_PANEL_RECURSOS).first
    tab = panel.locator('[role="tab"]').filter(has_text=tab_re).first
    if await tab.count() == 0:
        return False
    if await tab.get_attribute("aria-selected") == "true":
        return True
    try:
        await tab.click(timeout=8_000)
    except Exception:
        await tab.click(force=True, timeout=8_000)
    await page.wait_for_timeout(1_200)
    return True


def _sel_voice_chip(voice_name: str) -> str:
    """Chip de la voz ya aplicada, en la barra de instrucción."""
    return f'button[aria-label="{voice_name}"]'


async def select_voice(voice_name: str, sample_text: str = DEFAULT_VOICE_SAMPLE) -> None:
    """Elige la voz nativa del generador en el panel de recursos de Flow.

    `sample_text` va al campo "Diálogo de ejemplo" y fija el idioma con el que la
    voz habla. Con el campo vacío, Flow narra el guion español con acento inglés.

    Debe llamarse DESPUÉS de escribir el prompt y ANTES de enviarlo: la voz se
    engancha a la instrucción como un chip, y limpiar el campo antes lo borraría.

    Es IDEMPOTENTE: si el chip de esa voz ya está puesto, no hace nada. Sin eso,
    llamarla en cada escena acumularía un chip por clip.

    Lanza si no logra dejar el chip puesto. Es deliberado: cortar antes de enviar
    cuesta cero créditos; generar el clip con otra voz cuesta uno y hay que
    rehacerlo.
    """
    page = await get_page()
    chip = page.locator(_sel_voice_chip(voice_name))

    if await chip.count() > 0:
        print(f"  [voz] '{voice_name}' ya estaba aplicada")
        return

    await page.wait_for_selector(SEL_ADD_INGREDIENT, state="visible", timeout=10_000)
    await page.locator(SEL_ADD_INGREDIENT).first.click()
    await page.wait_for_timeout(2_000)

    panel = page.locator(SEL_PANEL_RECURSOS).first
    try:
        await panel.wait_for(state="visible", timeout=8_000)
    except Exception:
        await page.keyboard.press("Escape")
        raise RuntimeError("No se abrió el panel de recursos de Flow para elegir la voz.")

    async def _fallar(msg: str):
        from pathlib import Path
        Path("scratch").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="scratch/select_voice_error.png")
        await page.keyboard.press("Escape")
        raise RuntimeError(f"{msg} (captura en scratch/select_voice_error.png)")

    # 1. Pestaña "Voces"
    if not await _switch_panel_tab(page, _VOICES_TAB_RE):
        await _fallar("No encontré la pestaña 'Voces' en el panel de recursos de Flow.")

    # 2. Filtrar por nombre: la lista es larga y usa scroll virtual (virtuoso).
    search = panel.locator('input#add-menu-input, input[placeholder*="Buscar"], input[placeholder*="Search"]').first
    if await search.count() > 0:
        await search.fill(voice_name)
        await page.wait_for_timeout(1_800)

    fila = panel.locator('[role="option"]').filter(has_text=re.compile(re.escape(voice_name), re.IGNORECASE)).first
    if await fila.count() == 0:
        await _fallar(f"La voz '{voice_name}' no aparece en la pestaña Voces de Flow.")
    # 3. HOVER, no clic: pasar el ratón por encima de la fila abre el pane de
    #    vista previa a la derecha, que es donde viven el diálogo de ejemplo y el
    #    botón de confirmar. Clickear la fila aplica la voz y cierra el panel en
    #    el acto, saltándose el diálogo — y con él, el acento.
    await fila.hover()
    await page.wait_for_timeout(1_200)

    # 4. Diálogo de ejemplo. `fill()` enfoca por DOM y no mueve el ratón, así que
    #    el hover de la fila aguanta y el pane sigue montado.
    muestra_ok = False
    if sample_text:
        muestra = panel.locator(_SEL_MUESTRA).first
        try:
            await muestra.wait_for(state="visible", timeout=6_000)
            await muestra.fill(sample_text)
            await page.wait_for_timeout(600)
            muestra_ok = (await muestra.input_value()).strip() == sample_text.strip()
        except Exception:
            muestra_ok = False
        if not muestra_ok:
            print(f"  [voz] Aviso: no pude fijar el diálogo de ejemplo "
                  f"({sample_text!r}); la voz puede salir con acento inglés.")

    # 5. Confirmar con "Seleccionar voz". Si el pane no llegó a abrirse, queda el
    #    clic en la fila, que aplica la voz igual (sin acento fijado).
    confirmar = panel.locator('button, [role="button"]').filter(has_text=_PICK_VOICE_RE).first
    if await confirmar.count() > 0:
        await confirmar.first.click(force=True)
    else:
        await fila.click()
    await page.wait_for_timeout(1_500)

    # Dejar el panel cerrado pase lo que pase (si sigue abierto tapa el submit).
    try:
        await panel.wait_for(state="hidden", timeout=5_000)
    except Exception:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(800)

    # 5. Verificar de verdad: el chip en la barra de instrucción es la única
    #    prueba de que la voz quedó aplicada. Sin esto, un clic que no prendió
    #    pasaría inadvertido y el clip saldría con otra voz.
    try:
        await chip.first.wait_for(state="visible", timeout=8_000)
    except Exception:
        await _fallar(f"Hice clic en '{voice_name}' pero no apareció su chip en la instrucción.")

    detalle = f" (muestra: {sample_text!r})" if muestra_ok else ""
    print(f"  [voz] '{voice_name}' aplicada{detalle}")


RIGHTS_NOTICE = 'div[role="dialog"]:has-text("derechos necesarios"), div[role="dialog"]:has-text("necessary rights")'


async def _await_user_rights_notice(page, timeout_ms: int = 300_000) -> None:
    """Si Flow muestra el aviso de derechos tras enviar el archivo, espera a que
    el usuario lo acepte o cancele en la ventana. No lo confirma automáticamente.

    Sin esto el upload muere por timeout sin explicar por qué (el diálogo tapa el
    canvas y la card nunca aparece)."""
    notice = page.locator(RIGHTS_NOTICE).first
    try:
        await notice.wait_for(state="visible", timeout=4_000)
    except Exception:
        return  # No apareció: subida normal.

    print("\n>>> Google Flow pide confirmar los DERECHOS de la imagen que se sube.")
    print(">>> Acepta o cancela el aviso en la ventana de Chrome para continuar.\n")
    await notice.wait_for(state="hidden", timeout=timeout_ms)
    await page.wait_for_timeout(1_500)


async def upload_standalone_image(image_path: str) -> None:
    """Sube una imagen al canvas directamente (modo imagen). Flujo 5."""
    page = await get_page()
    
    # Cerrar panel de configuración o visores si quedaron abiertos
    try:
        settings_panel = page.locator('flow-prompt-box-settings')
        if await settings_panel.count() > 0 and await settings_panel.first.is_visible():
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
    except Exception:
        pass

    # 1. Contar elementos en canvas antes de subir para tener baseline
    pre_upload_cards = await page.locator('flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]').count()
    
    # 2. Esperar al boton de añadir recursos y click
    await page.wait_for_selector(SEL_ADD_INGREDIENT, state="visible", timeout=15_000)
    await page.locator(SEL_ADD_INGREDIENT).first.click()
    await page.locator(SEL_PANEL_RECURSOS).first.wait_for(state="visible", timeout=8_000)
    
    # 3. Volver a "Todos": si la última pestaña usada fue "Voces" (al fijar la
    #    voz nativa), el botón de subir no existe en el panel.
    await _switch_panel_tab(page, _ALL_TAB_RE)

    # 4. Click en Cargar medios / Subir imagen
    import re
    upload_btn = page.locator(SEL_PANEL_RECURSOS).first.locator('button, [role="button"]').filter(
        has_text=re.compile(r"(Cargar contenido multimedia|Cargar medios|Upload media|Subir imagen)", re.IGNORECASE)
    ).first
    
    if await upload_btn.count() == 0:
        raise Exception("Botón 'Cargar medios' o 'Upload' no encontrado.")
        
    async with page.expect_file_chooser(timeout=8_000) as fc_info:
        await upload_btn.click(force=True)
    
    file_chooser = await fc_info.value
    await file_chooser.set_files(str(image_path))

    # 3b. Aviso de derechos de Google Flow: aparece en la primera subida y bloquea
    # el upload hasta que el TITULAR de la cuenta lo acepte. NO se confirma por
    # automatización (es una declaración legal del usuario): se espera a que él
    # resuelva el diálogo en la ventana abierta.
    await _await_user_rights_notice(page)

    # 4. Esperar de forma dinámica y rigurosa usando la cuenta previa (Igual que en test-flow 5)
    await page.wait_for_function(
        f"""() => {{
            const cards = document.querySelectorAll('flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]');
            if (cards.length <= {pre_upload_cards}) return false;
            const img = cards[0].querySelector('img');
            return img && img.complete && img.naturalWidth > 0;
        }}""",
        timeout=60_000,
    )
    
    # 5. Cerrar el panel presionando Escape una vez confirmado el upload en el canvas
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(1000)



async def get_canvas_count() -> int:
    """Retorna cantidad actual de items en el canvas."""
    page = await get_page()
    return await page.locator('flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]').count()


SEL_SLOTS_INICIAR = 'div:text-is("Iniciar")'
SEL_SLOTS_FIN = 'div:text-is("Fin")'
SEL_UPLOAD_BTN = ':text-is("Subir imagen")'
SEL_SLOT_LOADED = 'img[alt*="contenido multimedia"]'

async def upload_frame(file_path: str, slot: str = "initial") -> None:
    """Sube un frame para modo Fotogramas. slot: 'initial' o 'final'."""
    page = await get_page()

    await page.wait_for_selector(SEL_SLOTS_INICIAR, state="visible", timeout=10000)
    target_slot = page.locator(SEL_SLOTS_INICIAR) if slot == "initial" else page.locator(SEL_SLOTS_FIN)

    initial_count = await page.locator(SEL_SLOT_LOADED).count()
    await target_slot.click()
    await page.wait_for_timeout(2000)

    async with page.expect_file_chooser(timeout=5000) as fc_info:
        import re
        upload_btn = page.locator('button, [role="button"], div').filter(
            has_text=re.compile(r"(Cargar contenido multimedia|Cargar medios|Upload media|Subir imagen)", re.IGNORECASE)
        ).first
        if await upload_btn.count() == 0:
            raise Exception("Botón de subida ('Cargar medios' / 'Upload') no encontrado para el slot.")
        await upload_btn.click(force=True)
    file_chooser = await fc_info.value
    await file_chooser.set_files(file_path)

    await page.wait_for_function(
        f"""() => {{
            const imgs = document.querySelectorAll('{SEL_SLOT_LOADED}');
            if (imgs.length <= {initial_count}) return false;
            return [...imgs].some(img => img.complete && img.naturalWidth > 0);
        }}""",
        timeout=60000
    )


async def select_frame_from_project(uuid: str, slot: str = "initial") -> None:
    """Selecciona un frame existente del proyecto para modo Fotogramas."""
    page = await get_page()
    
    await page.wait_for_selector(SEL_SLOTS_INICIAR, state="visible", timeout=10000)
    target_slot = page.locator(SEL_SLOTS_INICIAR) if slot == "initial" else page.locator(SEL_SLOTS_FIN)
    
    initial_count = await page.locator(SEL_SLOT_LOADED).count()
    await target_slot.click()
    await page.wait_for_timeout(2000)
    
    # Buscar la imagen en el dropup por UUID dentro del diálogo modal
    target_img = page.locator(f'[role="dialog"] img[src*="{uuid}"]')
    if await target_img.count() == 0:
        await page.keyboard.press("Escape")
        raise ValueError(f"No se encontró la imagen con UUID {uuid} en el proyecto para usar como frame.")
        
    await target_img.first.click()
    await page.wait_for_timeout(1000)
    
    # Confirmar selección con el botón 'Agregar a la instrucción'
    import re
    add_btn = page.locator('button, [role="button"]').filter(
        has_text=re.compile(r"(Agregar a la instrucción|Add to instruction|Add to prompt)", re.IGNORECASE)
    ).first
    if await add_btn.count() > 0:
        await add_btn.click()
        await page.wait_for_timeout(1000)
    
    # Esperar que cargue en el slot
    await page.wait_for_function(
        f"""() => {{
            const imgs = document.querySelectorAll('{SEL_SLOT_LOADED}');
            if (imgs.length <= {initial_count}) return false;
            return [...imgs].some(img => img.complete && img.naturalWidth > 0);
        }}""",
        timeout=60000
    )


async def capture_newest_asset_name(label: str, is_video: bool = False) -> str:
    """Rastrea el card más nuevo en el canvas y guarda su UUID en el registry bajo label.
    
    Para imágenes extrae el src del <img alt="Imagen generada">.
    Para videos extrae el src del <video> (mismo patrón URL ?name=UUID).
    """
    page = await get_page()
    
    # Flow prepende, así que .first siempre es el asset recién generado.
    card = page.locator('flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]').first
    
    if is_video:
        element = card.locator('video').first
    else:
        element = card.locator('img').first
    
    media_id = await element.get_attribute("data-media-id")
    if media_id and re.fullmatch(r"[a-f0-9-]{36}", media_id):
        key = _asb_key(await element.get_attribute("src") or "")
        if key:
            _asset_asb_keys[media_id] = key
        capture_name(label, media_id)
        return media_id

    src = await element.get_attribute("src")
    if not src:
        raise ValueError("No se pudo obtener el atributo src del asset más reciente.")
        
    match = re.search(r'(?:[?&]name=|/(?:image|video)/)([a-f0-9-]{36})', src)
    if not match:
        raise ValueError(f"No se encontró UUID en el src: {src}")
        
    uuid = match.group(1)
    capture_name(label, uuid)
    print(f"  📌 Registry: Guardado '{label}' -> {uuid}")
    return uuid
