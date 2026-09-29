"""
Espera de resultados de generación en Google Flow.

Flow tiene 3 fases post-submit para imágenes:
  Fase 1: card con blur + contador % (6 → 99)
  Fase 2: reveal animation ~5s — img aparece pero toolbar NO interactivo
  Fase 3: imagen lista — toolbar (more_vert) visible al hover

Incluye detección de errores de generación ("No se pudo generar") con retry automático.
"""
import asyncio
import random
import re
import time

from .browser import get_page

SEL_RESULT_IMAGE = 'flow-image-tile img.image, flow-image-tile img, img.image, img[alt*="Tarjeta que muestra la imagen" i], img[alt="Imagen generada"]'
SEL_RESULT_VIDEO = 'flow-video-tile video, flow-video-tile img, img[alt*="video" i], img[alt="Miniatura de video"]'
SEL_RESULT_CARD  = 'flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]'
SEL_MORE_MENU    = 'button[aria-label="Más opciones"], button:has(:is(i, mat-icon):text-is("more_vert"))'

# Selectores de error de generación — usar texto literal para evitar falsos positivos
# con cards de loading que también tienen data-tile-id
SEL_ERROR_TEXT = ':text("No se pudo generar")'
_ERROR_CARD_RE = re.compile(r"No se pudo generar|Se produjo un error", re.IGNORECASE)
# La card de error trae tres botones; el útil es "Reutilizar instrucción":
# devuelve al campo TODA la instrucción, incluida la voz elegida.
_REUSE_RE = re.compile(
    r"(Reutilizar instrucci|Volver a usar|Reuse (the )?prompt|Reuse instruction)", re.IGNORECASE
)
# DOM real de la card (calibrado 2026-07-31): tres botones, cada uno con su
# ligadura de ícono y una etiqueta accesible oculta.
#   refresh        -> "Reintentar"
#   undo           -> "Reutilizar instrucción"   <- el que sirve
#   delete_forever -> "Borrar"
_REUSE_ICON = 'button:has(i:text-is("undo"))'


async def error_card_count(page) -> int:
    """Cards de error visibles ahora mismo.

    Se usa como LÍNEA BASE antes de esperar: las cards de error de escenas o
    intentos anteriores siguen en el canvas hasta que se refresca la página, y
    sin este baseline hacían fallar la escena siguiente en segundos sin que esa
    generación tuviera nada malo.
    """
    return await page.locator(SEL_ERROR_TEXT).count()


async def _reuse_instruction_and_resend(page, attempt: int = 0) -> bool:
    """Recupera una generación que Flow tumbó por saturación.

    Flow devuelve seguido una card "No se pudo generar / Se produjo un error"
    cuando está saturado; no es un rechazo del prompt. Esa card trae el botón
    "Reutilizar instrucción", que repone la instrucción completa (prompt + voz)
    en el campo. Desde ahí solo falta reenviar. Es exactamente la maniobra
    manual que funciona.
    """
    card = page.locator(SEL_RESULT_CARD).filter(has_text=_ERROR_CARD_RE).first
    if await card.count() == 0:
        return False

    btn = card.locator(_REUSE_ICON).first
    via = "ícono undo"
    if await btn.count() == 0:
        btn = card.get_by_role("button", name=_REUSE_RE).first
        via = "nombre accesible"
    if await btn.count() == 0:
        print("  [flow] Card de error sin botón 'Reutilizar instrucción' localizable.")
        return False

    # El botón de enviar arranca con aria-disabled="true" y se habilita cuando la
    # instrucción vuelve al campo. Esperar eso es más fiable que un sleep:
    # confirma que Flow repuso de verdad el prompt y la voz.
    from .prompt import SEL_SUBMIT
    submit = page.locator(SEL_SUBMIT).first
    try:
        await submit.wait_for(state="visible", timeout=15_000)
    except Exception:
        print("  [flow] No encuentro el botón de enviar.")
        return False

    async def _campo_listo(segundos: float) -> bool:
        for _ in range(int(segundos * 2)):
            try:
                if await submit.get_attribute("aria-disabled") != "true":
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    # Dos pulsaciones: el primer clic a veces cae mientras la card todavía se
    # está montando y no repone nada. Rendirse ahí desperdicia el reintento.
    for pulsacion in range(2):
        await btn.click(force=True)
        if await _campo_listo(20.0):
            break
        if pulsacion == 0:
            print("  [flow] El campo siguió vacío; vuelvo a pulsar 'Reutilizar instrucción'.")
            await asyncio.sleep(2.0)
    else:
        print("  [flow] 'Reutilizar instrucción' no repuso la instrucción tras dos intentos.")
        return False

    # Respiro antes de reenviar. Flow devuelve este error cuando está saturado,
    # así que reintentar en el acto suele volver a fallar; el retardo crece con
    # cada intento y lleva algo de azar para no reenviar siempre en el mismo
    # instante exacto.
    espera = random.uniform(4.0, 9.0) * (attempt + 1)
    print(f"  [flow] Instrucción reutilizada (vía {via}). Reenviando en {espera:.1f}s...")
    await asyncio.sleep(espera)

    await submit.click()
    await page.wait_for_timeout(2_000)
    return True


async def _poll_until_ready(page, media_sel: str, pre_cards, pre_errors: int, timeout_ms: int) -> str:
    """Espera a que aparezca el asset nuevo o una card de error NUEVA.

    Devuelve 'ok' o 'error'. Lanza TimeoutError si no pasa ninguna de las dos.
    """
    guard = "true" if pre_cards is None else f"cards.length > {pre_cards}"
    is_video = "video" in media_sel
    tipo = "video" if is_video else "imagen"

    js = f"""() => {{
        try {{
            const cards = document.querySelectorAll('{SEL_RESULT_CARD}');
            if (!cards.length) return {{ ready: false, reason: "sin_cards" }};
            if (!({guard})) return {{ ready: false, reason: "esperando_aparicion_card", total: cards.length }};

            const card = cards[0];

            // 1. Descartar si todavía hay porcentaje numérico de generación visible (ej. "14%", "50%")
            const textContent = card.innerText || "";
            const matchPercent = textContent.match(/\\b\\d+%\\b/);
            if (matchPercent) {{
                return {{ ready: false, reason: "porcentaje", percent: matchPercent[0] }};
            }}

            // 2. Descartar solo si hay un spinner que realmente sea VISIBLE en pantalla
            const spinners = card.querySelectorAll('mat-progress-spinner, mat-spinner, flow-loading-indicator, [role="progressbar"]');
            for (const sp of spinners) {{
                const st = window.getComputedStyle(sp);
                if (st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0' && (sp.offsetWidth > 0 || sp.offsetHeight > 0)) {{
                    return {{ ready: false, reason: "spinner_activo" }};
                }}
            }}

            // 3. Comprobación para VIDEO
            if ('{media_sel}'.includes('video')) {{
                const video = card.querySelector('video, flow-video-tile video');
                if (video) {{
                    const src = video.getAttribute('src') || video.currentSrc || video.src || '';
                    const aria = (video.getAttribute('aria-label') || '').toLowerCase();
                    if ((src.startsWith('http') && src.length > 40) || (src.startsWith('blob:') && src.length > 50) || aria.includes('generado')) {{
                        return {{ ready: true, detail: "video_src" }};
                    }}
                    if (video.readyState >= 2 && !video.paused) {{
                        return {{ ready: true, detail: "video_playing" }};
                    }}
                }}

                // B) Si ya pasaron los segundos necesarios de render, no hay porcentaje ni spinners,
                // y la card tiene su póster de imagen completo montado:
                const hasTile = card.querySelector('flow-video-tile') || card.tagName.toLowerCase().includes('video');
                const img = card.querySelector('img');
                if (hasTile && img && img.complete && img.naturalWidth > 0) {{
                    return {{ ready: true, detail: "video_poster_listo" }};
                }}

                return {{ ready: false, reason: "video_procesando" }};
            }}

            // 4. Comprobación para IMAGEN
            const media = card.querySelector('{media_sel}');
            if (media) {{
                if (media.tagName.toLowerCase() === 'img') {{
                    if (media.complete && (media.naturalWidth > 0 || (media.src && media.src.length > 20))) {{
                        return {{ ready: true, detail: "img_complete" }};
                    }}
                }} else if (media.readyState >= 2 || (media.src && media.src.length > 20)) {{
                    return {{ ready: true, detail: "media_ready" }};
                }}
            }}

            // 5. Verificación por controles de la card (solo para IMAGEN cuando ya no hay spinners)
            if (!('{media_sel}'.includes('video'))) {{
                const buttons = card.querySelectorAll('button');
                for (const b of buttons) {{
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    const text = (b.innerText || '').toLowerCase();
                    if (aria.includes('más') || aria.includes('options') || text.includes('more_vert')) {{
                        return {{ ready: true, detail: "toolbar_presente" }};
                    }}
                }}
            }}

            return {{ ready: false, reason: "esperando_render" }};
        }} catch (e) {{
            return {{ ready: false, error: e.toString() }};
        }}
    }}"""
    deadline = time.monotonic() + timeout_ms / 1000
    start = time.monotonic()
    last_log = 0

    while time.monotonic() < deadline:
        elapsed = int(time.monotonic() - start)

        # Un video de Flow NUNCA está listo en menos de 15 segundos
        if is_video and elapsed < 15:
            if elapsed - last_log >= 5:
                last_log = elapsed
                print(f"    [wait] Iniciando render de video en Flow (fase inicial de desenfoque, {elapsed}s)...")
            await asyncio.sleep(2)
            continue

        # Para videos: a partir de los 50s, pasar suavemente el cursor sobre la card
        # para "despertar" el reproductor de Flow y forzar a que monte el <video src="...">
        if is_video and elapsed >= 50:
            try:
                card_loc = page.locator(SEL_RESULT_CARD).first
                if await card_loc.count() > 0:
                    box = await card_loc.bounding_box()
                    if box:
                        await page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
            except Exception:
                pass

        try:
            res = await page.evaluate(js)
        except Exception as eval_err:
            res = {"ready": False, "error": str(eval_err)}

        if res.get("error"):
            print(f"    [wait] Aviso DOM ({elapsed}s): {res['error']}")

        if res.get("ready"):
            detail = res.get("detail", "ok")
            print(f"    [wait] ¡{tipo.capitalize()} lista en canvas! ({elapsed}s, vía {detail})")
            print(f"    [wait] Asentando animación en interfaz (3s)...")
            await asyncio.sleep(3.0)
            return "ok"

        # Logs informativos periódicos cada 5 segundos
        if elapsed - last_log >= 5:
            last_log = elapsed
            if res.get("percent"):
                print(f"    [wait] Generando {tipo}: {res['percent']} ({elapsed}s)...")
            elif res.get("reason") == "spinner_activo":
                print(f"    [wait] Generando {tipo} (procesando en Flow, {elapsed}s)...")
            elif res.get("reason") == "esperando_aparicion_card":
                print(f"    [wait] Esperando que Flow monte la nueva card en canvas ({elapsed}s)...")
            else:
                print(f"    [wait] Esperando resultado de {tipo} ({elapsed}s)...")

        if await error_card_count(page) > pre_errors:
            print(f"    [wait] Detectada card de error de generación en Flow.")
            return "error"

        await asyncio.sleep(2)

    raise TimeoutError(f"Generación de {tipo} no completó en {timeout_ms // 1000}s")


async def _wait_for_media(media_sel: str, kind: str, timeout_ms: int,
                          max_retries: int, pre_submit_count) -> None:
    page = await get_page()
    pre_errors = await error_card_count(page)

    for intento in range(max_retries + 1):
        estado = await _poll_until_ready(page, media_sel, pre_submit_count, pre_errors, timeout_ms)
        if estado == "ok":
            return
        if intento >= max_retries:
            raise Exception(
                f"Generación de {kind} falló {max_retries + 1} veces seguidas. "
                "Flow reporta: 'No se pudo generar' (suele ser saturación)."
            )
        print(f"  [flow] Error de generación ({intento + 1}/{max_retries + 1}). Recuperando...")
        if not await _reuse_instruction_and_resend(page, intento):
            raise Exception(
                "Flow reporta 'No se pudo generar' y no pude reutilizar la instrucción."
            )
        # La card de error nueva pasa a formar parte del paisaje: si no se
        # recuenta, el siguiente poll la volvería a leer como fallo inmediato.
        pre_errors = await error_card_count(page)


async def wait_for_image(timeout_ms: int = 120000, max_retries: int = 2, pre_submit_count: int | None = None) -> None:
    """Espera la imagen generada. Recupera sola si Flow falla por saturación."""
    await _wait_for_media(SEL_RESULT_IMAGE, "imagen", timeout_ms, max_retries, pre_submit_count)
    page = await get_page()
    # Confirmar que el bitmap está decodificado antes de dejar seguir al motor.
    try:
        await page.wait_for_function(
            f"""() => {{
                const card = document.querySelector('{SEL_RESULT_CARD}');
                const img = card && card.querySelector('{SEL_RESULT_IMAGE}');
                return img && img.complete && img.naturalWidth > 0;
            }}""",
            timeout=20_000,
        )
    except Exception:
        pass


async def wait_for_video(timeout_ms: int = 180000, max_retries: int = 2, pre_submit_count: int | None = None) -> None:
    """Espera el video generado. Recupera sola si Flow falla. Default 3 min (180s)."""
    await _wait_for_media(SEL_RESULT_VIDEO, "video", timeout_ms, max_retries, pre_submit_count)
    page = await get_page()
    try:
        await page.wait_for_function(
            f"""() => {{
                const card = document.querySelector('{SEL_RESULT_CARD}');
                const vid = card ? card.querySelector('video') : document.querySelector('video');
                if (!vid) return false;
                const src = vid.getAttribute('src') || vid.currentSrc || vid.src || '';
                return src.length > 20 || vid.readyState >= 2;
            }}""",
            timeout=20_000,
        )
    except Exception:
        pass  # Fallback: Flow a veces renderiza miniatura y oculta src
