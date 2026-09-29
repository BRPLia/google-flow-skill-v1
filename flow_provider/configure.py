"""
Selección de modo (IMAGE/VIDEO), aspect ratio, cantidad y modelo en el panel de Flow.
"""
from .browser import get_page, SEL_SETTINGS_TRIGGER

# El nombre accesible de la píldora es independiente del modo/modelo.
SEL_PANEL_TRIGGER = SEL_SETTINGS_TRIGGER

SEL_TAB_IMAGE       = '[id$="-trigger-IMAGE"]'
SEL_TAB_VIDEO       = '[id$="-trigger-VIDEO"]'
SEL_TAB_FRAMES      = '[id$="-trigger-VIDEO_FRAMES"]'
SEL_TAB_INGREDIENTS = '[id$="-trigger-VIDEO_REFERENCES"]'

SEL_RATIO = {
    "16:9": '[id$="-trigger-LANDSCAPE"]',
    "4:3":  '[id$="-trigger-LANDSCAPE_4_3"]',
    "1:1":  '[id$="-trigger-SQUARE"]',
    "3:4":  '[id$="-trigger-PORTRAIT_3_4"]',
    "9:16": '[id$="-trigger-PORTRAIT"]',
}
SEL_COUNT = {i: f'[id$="-trigger-{i}"]' for i in range(1, 5)}

SEL_MODEL_IMG = {
    'Nano Banana Pro':    '[role="menuitem"]:has-text("Nano Banana Pro")',
    'Nano Banana 2':      '[role="menuitem"]:has-text("Nano Banana 2")',
    'Nano Banana 2 Lite': '[role="menuitem"]:has-text("Nano Banana 2 Lite"), [role="menuitem"]:has-text("nano banan 2 lite"), [role="menuitem"]:has-text("nano banana 2 lite")',
    'nano banan 2 lite':  '[role="menuitem"]:has-text("Nano Banana 2 Lite"), [role="menuitem"]:has-text("nano banan 2 lite"), [role="menuitem"]:has-text("nano banana 2 lite")',
    'Imagen 4':           '[role="menuitem"]:has-text("Imagen 4")',
}
SEL_MODEL_VID = {
    'Veo 3.1 - Lite':    '[role="menuitem"]:has-text("Veo 3.1 - Lite")',
    'Veo 3.1 - Fast':    '[role="menuitem"]:has-text("Veo 3.1 - Fast")',
    'Veo 3.1 - Quality': '[role="menuitem"]:has-text("Veo 3.1 - Quality")',
    'Omni 1.1 Flash':    '[role="menuitem"]:has-text("Omni")',
    'Omni 1.1 - Flash':  '[role="menuitem"]:has-text("Omni")',
    'Omni Flash':        '[role="menuitem"]:has-text("Omni")',
}


import re

async def _dismiss_blocking_changelog(page) -> None:
    """Detecta y elimina de forma destructiva del DOM cualquier modal o iframe de changelog que bloquee la pantalla."""
    try:
        # Evaluar JS para eliminar el iframe del changelog y su contenedor flotante del DOM
        await page.evaluate("""() => {
            const iframes = document.querySelectorAll('iframe[src*="changelogs"]');
            iframes.forEach(iframe => {
                let parent = iframe.parentElement;
                let foundParent = false;
                while (parent && parent !== document.body) {
                    const role = parent.getAttribute('role');
                    const className = parent.className || '';
                    if (role === 'dialog' || className.includes('dialog') || className.includes('eoilMe') || className.includes('sc-')) {
                        parent.remove();
                        foundParent = true;
                        break;
                    }
                    parent = parent.parentElement;
                }
                if (!foundParent) {
                    iframe.remove();
                }
            });
        }""")
        await page.wait_for_timeout(300)
    except Exception:
        pass


def _image_model_name(text: str) -> str:
    return " ".join(text.replace("arrow_drop_down", "").replace("🍌", "").split()).casefold()


async def _open_settings(page):
    """Reutiliza el panel abierto; recupera la reapertura tras un Escape previo."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    panel = page.locator("flow-prompt-box-settings:visible").first
    for attempt in range(2):
        if await panel.is_visible():
            return panel
        print(f"    [config] Abriendo ajustes de Flow (intento {attempt + 1}/2)...")
        await page.locator(SEL_PANEL_TRIGGER).click(timeout=10_000)
        try:
            await panel.wait_for(state="visible", timeout=3_000)
            return panel
        except PlaywrightTimeoutError:
            if attempt == 1:
                raise


async def _close_settings(page):
    """Cierra mediante el mismo botón para que la siguiente apertura funcione."""
    panel = page.locator("flow-prompt-box-settings:visible").first
    if await panel.is_visible():
        await page.locator(SEL_PANEL_TRIGGER).click(timeout=10_000)
    await panel.wait_for(state="hidden", timeout=5_000)


async def select_image_mode(
    aspect_ratio: str = "9:16",
    count: int = 1,
    model: str = "Nano Banana 2",
) -> None:
    """Abre el panel y configura modo IMAGE usando los selectores exactos del DOM de Flow. Debe llamarse con lock."""
    page = await get_page()
    await _dismiss_blocking_changelog(page)

    await _open_settings(page)

    # 2. Confirmar pestaña 'Imagen' dentro del panel
    print("    [config 2/5] Confirmando pestaña 'Imagen'...")
    tab_img = page.locator('flow-prompt-box-settings flow-toggles[aria-label="Modo"] button:has-text("Imagen"), flow-prompt-box-settings button:has-text("Imagen")').first
    if await tab_img.count() > 0 and await tab_img.is_visible():
        await tab_img.click()
        await page.wait_for_timeout(300)

    # 3. Aspect ratio dentro del panel (ej. 9:16)
    print(f"    [config 3/5] Seleccionando relación de aspecto: {aspect_ratio}...")
    ratio_btn = page.locator(f'flow-prompt-box-settings flow-toggles[aria-label="Relación de aspecto"] button:has-text("{aspect_ratio}"), flow-prompt-box-settings button:has-text("{aspect_ratio}")').first
    if await ratio_btn.count() > 0 and await ratio_btn.is_visible():
        await ratio_btn.click()
        await page.wait_for_timeout(300)

    # 4. Seleccionar modelo dentro del panel
    print(f"    [config 4/5] Verificando modelo: {model}...")
    model_btn = page.locator('flow-prompt-box-settings button[aria-label="Seleccionar familia de modelos"], flow-prompt-box-settings button:has(span.model-select-trigger-content)').first
    if await model_btn.count() > 0 and await model_btn.is_visible():
        current_text = await model_btn.inner_text()
        # Si el modelo ya está activo, no tocar el submenú
        target_model = "Nano Banana 2 Lite" if model.lower() == "nano banan 2 lite" else model
        if _image_model_name(current_text) == _image_model_name(target_model):
            print(f"    [config 4/5] Modelo ya activo: {current_text.strip()}")
        else:
            print(f"    [config 4/5] Desplegando submenú para cambiar a {target_model}...")
            await model_btn.click()
            menu_item = page.get_by_role("menuitem", name=re.compile(
                r"^\s*(?:🍌\s*)?" + re.escape(target_model) + r"\s*$", re.I))
            await menu_item.wait_for(state="visible", timeout=8_000)
            await menu_item.click()
            await page.wait_for_function(
                """target => {
                    const b = document.querySelector('flow-prompt-box-settings button[aria-label="Seleccionar familia de modelos"]');
                    const clean = s => s.replace(/arrow_drop_down/g, '').replace(/🍌/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
                    return b && clean(b.innerText) === target;
                }""", arg=_image_model_name(target_model), timeout=8_000)
    else:
        raise RuntimeError("No se encontró el selector de modelo de imagen; no se enviará generación.")

    # 5. Cantidad dentro del panel (x1)
    print(f"    [config 5/5] Ajustando cantidad a: x{count}...")
    count_btn = page.locator(f'flow-prompt-box-settings flow-toggles[aria-label="Número de salidas"] button:has-text("x{count}"), flow-prompt-box-settings button:has-text("x{count}")').first
    if await count_btn.count() > 0 and await count_btn.is_visible():
        await count_btn.click()
        await page.wait_for_timeout(300)

    # 6. Cerrar con el botón de ajustes antes de enfocar el editor.
    print("    [config] Guardando configuración y enfocando editor de prompt...")
    await _close_settings(page)
    prompt_box = page.locator('flow-rich-text-editor div[contenteditable="true"], div.ProseMirror[contenteditable="true"], div[contenteditable="true"]').first
    if await prompt_box.count() > 0:
        try:
            await prompt_box.click(position={"x": 30, "y": 15}, force=True)
        except Exception:
            await prompt_box.evaluate("el => el.focus()")
    await page.wait_for_timeout(300)


async def _select_radio(panel, name: str | re.Pattern[str]) -> None:
    from playwright.async_api import expect
    control = panel.get_by_role("radio", name=name, exact=isinstance(name, str))
    await control.wait_for(state="visible", timeout=10_000)
    if await control.get_attribute("aria-checked") != "true":
        await control.click()
    await expect(control).to_have_attribute("aria-checked", "true", timeout=5_000)


async def select_video_mode(
    aspect_ratio: str = "9:16", count: int = 1,
    mode: str = "fotogramas", model: str = "Veo 3.1 - Lite",
    duration: str | None = None,
) -> None:
    from playwright.async_api import expect
    page = await get_page()
    panel = await _open_settings(page)
    await _select_radio(panel, re.compile(r"^V[ií]deo$", re.I))
    if mode in ("fotogramas", "ingredientes"):
        await _select_radio(panel, "Fotogramas" if mode == "fotogramas" else "Ingredientes")
    elif mode != "texto":
        raise ValueError(f"Modo de video desconocido: {mode}")
    trigger = panel.get_by_role("button", name="Seleccionar familia de modelos", exact=True)
    target = "Omni 1.1 Flash" if model in ("Omni Flash", "Omni 1.1 - Flash") else model
    pattern = re.compile(r"^\s*" + re.escape(target) + r"\s*(?:arrow_drop_down)?\s*$")
    if not pattern.fullmatch(await trigger.inner_text()):
        await trigger.click()
        await page.get_by_role("menuitem", name=target, exact=True).click(timeout=8_000)
    await expect(trigger).to_have_text(pattern, timeout=8_000)
    await _select_radio(panel, aspect_ratio)
    await _select_radio(panel, f"x{count}")
    if duration:
        seconds = re.fullmatch(r"(\d+)\s*s", duration.strip())
        if not seconds:
            raise ValueError(f"Duración inválida: {duration}")
        await _select_radio(panel, f"{seconds.group(1)} s")
    print(f"    [config] Video verificado: {target}, {mode}, {aspect_ratio}, x{count}, {duration}")
    await _close_settings(page)
