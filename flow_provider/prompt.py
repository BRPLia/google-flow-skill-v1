"""
Escritura y envío del prompt en Google Flow.

IMPORTANTE: El campo de prompt es un editor Slate <div contenteditable="true">,
NO un input/textarea. No usar .fill() — usar .click() + Ctrl+A + keyboard.insert_text().
El texto NUNCA se teclea con keyboard.type(): cada \n sería un Enter y Flow enviaría
la generación a media escritura. Solo el `@` va tecleado, porque dispara el popover.
"""
import re

from .browser import get_page

SEL_PROMPT = 'flow-rich-text-editor div[contenteditable="true"], div.ProseMirror[contenteditable="true"], div[contenteditable="true"]'
SEL_SUBMIT = 'button:has(> :text-is("arrow_forward"))'

# Menú @ (interfaz nueva de Flow): popover Radix con buscador por nombre.
# Validado en scripts/calibrate_mentions3.py — inserta un chip inline en el prompt.
SEL_MENTION_DIALOG = 'flow-add-menu-popover-content, div[role="dialog"]:has(input#add-menu-input)'
SEL_MENTION_SEARCH = 'input[aria-label="Buscar activos"], input[placeholder="Buscar activos"], input.search-input, input#add-menu-input'
_ADD_TO_PROMPT_RE = re.compile(r"(Agregar a la instrucci|Add to instruction|Add to prompt)", re.I)


async def submit_prompt(prompt: str) -> None:
    """Escribe el prompt y hace click en submit. Debe llamarse con lock."""
    page = await get_page()

    # Escribir en el div contenteditable
    print(f"    [prompt] Insertando texto del prompt ({len(prompt)} caracteres)...")
    prompt_box = page.locator(SEL_PROMPT).first
    try:
        await prompt_box.click(position={"x": 30, "y": 15}, force=True)
    except Exception:
        await prompt_box.evaluate("el => el.focus()")
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await page.keyboard.insert_text(prompt)
    await page.wait_for_timeout(300)

    # Click submit
    print("    [prompt] Enviando generación (clic en botón flecha)...")
    submit_btn = page.locator(SEL_SUBMIT)
    await submit_btn.first.click()


async def submit_segments_with_voice(segments: list[dict], voice: str | None = None,
                                     voice_sample: str | None = None) -> None:
    """Escribe texto + @menciones, fija la voz nativa y envía. Con lock.

    Dos decisiones que importan:
      - El texto se inserta de golpe (`insert_text`) en vez de tecleado. Un
        prompt de estilo Vox son ~1500 caracteres: a 20 ms por tecla serían 30 s
        por escena. Solo el `@` de una mención necesita ir tecleado, porque es lo
        que dispara el popover.
      - La voz va AL FINAL, justo antes de enviar: se engancha como chip a la
        instrucción, así que elegirla antes de limpiar el campo la borraría.

    `voice_sample` es la frase del "Diálogo de ejemplo" y fija el idioma con que
    la voz narra. Si va en None se usa el default de `canvas` ("hola a todos").
    """
    from .canvas import DEFAULT_VOICE_SAMPLE, select_voice

    page = await get_page()
    box = page.locator(SEL_PROMPT).first
    await box.click()
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await page.wait_for_timeout(200)

    for seg in segments:
        if seg["type"] == "text":
            if seg.get("value"):
                await page.keyboard.insert_text(seg["value"])
        elif seg["type"] == "mention":
            await _insert_mention(page, seg["name"])
        else:
            raise ValueError(f"segmento desconocido: {seg!r}")

    await page.wait_for_timeout(300)
    if voice:
        await select_voice(voice, voice_sample if voice_sample is not None else DEFAULT_VOICE_SAMPLE)
    await page.locator(SEL_SUBMIT).first.click()


async def submit_prompt_with_voice(prompt: str, voice: str, voice_sample: str | None = None) -> None:
    """Prompt plano (sin menciones) + voz nativa. Con lock."""
    await submit_segments_with_voice([{"type": "text", "value": prompt}], voice, voice_sample)


async def _insert_mention(page, search_name: str) -> None:
    """Inserta una mención inline: abre el menú @, busca por nombre y confirma.

    `search_name` es el texto con que Flow lista el recurso (ej. nombre de archivo
    o de personaje). El recurso debe existir e indexarse en el proyecto.
    """
    box = page.locator(SEL_PROMPT).first
    chips = box.locator('span.mention-chip[data-mention-id]').filter(has_text=re.compile("^" + re.escape(search_name) + "$"))
    before = await chips.count()
    print(f"    [mention] Abriendo @ para {search_name}")
    # Cada mención vuelve al editor: no heredar foco del panel anterior.
    await box.press("Control+End")
    await box.press_sequentially("@", delay=60)
    dialog = page.locator(', '.join(s + ":visible" for s in SEL_MENTION_DIALOG.split(", "))).first
    try:
        await dialog.wait_for(state="visible", timeout=8_000)
    except Exception as err:
        from pathlib import Path
        import json
        dest = Path("scratch/flow-ui-2026-09-15")
        dest.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(dest / "mention-error.png"))
        state = await page.evaluate("""() => ({
            url: location.href,
            focused: document.activeElement?.outerHTML,
            editors: [...document.querySelectorAll('[contenteditable="true"]')].map(e => e.outerHTML),
            panels: [...document.querySelectorAll('flow-add-menu-popover-content, [role="dialog"]')].map(e => e.outerHTML),
            trigger: document.querySelector('button.add-menu-trigger')?.outerHTML
        })""")
        state["search_name"] = search_name
        (dest / "mention-error.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"No abrió el menú @ para {search_name}; ver scratch/flow-ui-2026-09-15/mention-error.png y .json") from err
    search = dialog.locator(SEL_MENTION_SEARCH).first
    await search.fill(search_name)
    # Seleccionar la fila exacta, no confirmar el preview de otro recurso.
    row = dialog.get_by_role("option").filter(
        has=page.get_by_text(search_name, exact=True)).first
    await row.wait_for(state="visible", timeout=10_000)
    await row.click()
    await chips.nth(before).wait_for(state="visible", timeout=8_000)
    if await dialog.is_visible():
        await page.keyboard.press("Escape")
    await box.click()
    await page.keyboard.press("Control+End")


async def submit_prompt_with_mentions(segments: list[dict], submit: bool = True) -> None:
    """Escribe un prompt intercalando texto y menciones @ inline, luego envía.

    `segments`: lista ordenada de
        {"type": "text", "value": str}                 -> se teclea literal
        {"type": "mention", "name": str}               -> se inserta vía menú @
    `name` es el texto de búsqueda del recurso en Flow (resuelto por el core a
    partir del label del guion). Debe llamarse con lock.
    """
    page = await get_page()
    box = page.locator(SEL_PROMPT).first
    await box.click()
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await page.wait_for_timeout(200)

    for seg in segments:
        if seg["type"] == "text":
            if seg.get("value"):
                # insert_text y no type(): con type() cada \n del prompt es un Enter
                # y Flow envía la generación a media escritura (prompts con beats).
                await page.keyboard.insert_text(seg["value"])
        elif seg["type"] == "mention":
            await _insert_mention(page, seg["name"])
        else:
            raise ValueError(f"segmento desconocido: {seg!r}")

    await page.wait_for_timeout(300)
    if submit:
        await page.locator(SEL_SUBMIT).first.click()
