"""
Descarga del último resultado generado en Google Flow.

Flujo: hover card → click more_vert → menuitem Descargar → sub-menú resolución

SELECTORES CRÍTICOS (validados 2026-04-15):
  - more_vert: el ícono es texto <i>more_vert</i>, NO atributo data-icon
  - menuitem: usa role="menuitem", NO el elemento custom <menuitem>
"""
import asyncio
from pathlib import Path
import re
import shutil
import time
from .browser import get_page
from . import settings

SEL_RESULT_CARD = 'flow-grid-tile-container, flow-tile-container, [aria-roledescription="draggable"]'
SEL_MORE_MENU   = 'button[aria-label="Más opciones"], button:has(:is(i, mat-icon):text-is("more_vert"))'
SEL_DL_ITEM     = '[role="menuitem"]:has-text("Descargar"), button:has(:is(i, mat-icon):text-is("download"))'
SEL_DL_RES = {
    "1K": '[role="menuitem"]:has-text("1K")',
    "2K": '[role="menuitem"]:has-text("2K")',
    "720p": '[role="menuitem"]:has-text("720p")',
}


def _sel_card(is_video: bool = False) -> str:
    """Card del asset. El filtro `:has(...)` salta las cards de error de Flow,
    que no tienen miniatura."""
    if is_video:
        return (
            'flow-tile-container:has(flow-video-tile), '
            'flow-tile-container:has(video), '
            'flow-grid-tile-container:has(flow-video-tile), '
            'flow-grid-tile-container:has(video), '
            '[aria-roledescription="draggable"]:has(video), '
            'flow-tile-container, '
            'flow-grid-tile-container, '
            '[aria-roledescription="draggable"]'
        )
    return (
        'flow-tile-container:has(flow-image-tile), '
        'flow-tile-container:has(img.image), '
        'flow-grid-tile-container:has(flow-image-tile), '
        'flow-grid-tile-container:has(img.image), '
        'flow-tile-container, '
        'flow-grid-tile-container, '
        '[aria-roledescription="draggable"], mat-card, flow-media-card'
    )


def _sel_menu_item(icono: str) -> str:
    """Entrada del menú por su ligadura de ícono o texto."""
    if icono == "download":
        return ':is([role="menuitem"], button):has(:is(i, mat-icon):text-is("download")), [role="menuitem"]:has-text("Descargar"), [role="menuitem"]:has-text("Download")'
    return f':is([role="menuitem"], button, [role="button"]):has(:is(i, mat-icon):text-is("{icono}"))'


async def _open_card_menu(page, card, is_video: bool = False, caller: str = "download") -> None:
    """Abre el menú de acciones de una card (Descargar, Reutilizar, Papelera…)."""
    dl_sel = _sel_menu_item("download")
    prefix = "[download 2/5]" if caller == "download" else "[cleanup]"

    # Si el menú de descarga ya está visible en pantalla, no hacer nada
    if await page.locator(dl_sel).count() > 0 and await page.locator(dl_sel).first.is_visible():
        print(f"  {prefix} Menú de acciones ya desplegado.")
        return

    # Si hay algún menú residual abierto (ej. menú de "Borrar" de clic derecho previo), cerrarlo con Escape
    try:
        borrar_popup = page.locator(':is([role="menu"], [role="menuitem"]):has-text("Borrar")')
        if await borrar_popup.count() > 0 and await borrar_popup.first.is_visible():
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
    except Exception:
        pass

    await card.scroll_into_view_if_needed()

    # 1. Hover sobre la card para revelar la botonera flotante superior con los 3 puntos (more_vert)
    print(f"  {prefix} Hover sobre la card para revelar botón de 3 puntos (more_vert)...")
    more_btn = card.locator(
        'button[aria-label*="opciones" i], '
        'button[aria-label*="options" i], '
        'button[aria-label*="Más" i], '
        'button:has(:is(i, mat-icon):text-is("more_vert")), '
        'button:has(:is(i, mat-icon):text-is("more_horiz")), '
        'button[aria-haspopup="menu"]'
    ).first

    for hover_attempt in range(3):
        box = await card.bounding_box()
        if box:
            if hover_attempt == 0:
                await page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
            elif hover_attempt == 1:
                # Esquina superior derecha donde vive la píldora de acciones
                await page.mouse.move(box["x"] + box["width"] * 0.85, box["y"] + box["height"] * 0.15)
            else:
                await page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.2)
        else:
            await card.hover()

        await asyncio.sleep(0.4)
        if await more_btn.count() > 0 and await more_btn.is_visible():
            break

    if await more_btn.count() > 0 and await more_btn.is_visible():
        print(f"  {prefix} Haciendo clic en botón de 3 puntos (more_vert)...")
        await more_btn.click()
        await asyncio.sleep(0.5)
        if await page.locator(dl_sel).count() > 0 and await page.locator(dl_sel).first.is_visible():
            print(f"  {prefix} Menú desplegado con éxito vía botón 3 puntos.")
            return

    # Fallback solo para imágenes: el clic derecho en video solo tiene "Borrar"
    if not is_video:
        print(f"  {prefix} Fallback: probando clic derecho en la card de imagen...")
        await card.click(button="right", force=True)
        await asyncio.sleep(0.5)
        if await page.locator(dl_sel).count() > 0 and await page.locator(dl_sel).first.is_visible():
            print(f"  {prefix} Menú desplegado con éxito vía clic derecho.")
            return
        await page.keyboard.press("Escape")

    if caller == "download":
        raise RuntimeError("No pude abrir el menú con opción 'Descargar' en la card tras varios intentos.")


def _save_to_dest(src_path: Path | str, dest_path: Path | str) -> None:
    """Copia o convierte la imagen a PNG si el destino es .png."""
    src = Path(src_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.suffix.lower() == ".png":
        from PIL import Image
        with Image.open(src) as im:
            im.save(str(dest), "PNG")
        return
    shutil.copy2(str(src), str(dest))


async def download_latest(output_path: str, resolution: str = "1K", is_video: bool = False) -> str:
    """Descarga el último resultado. Retorna el path guardado. Debe llamarse con lock."""
    page = await get_page()

    print(f"  [download 1/5] Localizando card de {'video' if is_video else 'imagen'}...")
    card = page.locator(_sel_card(is_video)).first
    await card.wait_for(state="visible", timeout=30_000)

    # ────────────────────────────────────────────────────────────────────────
    # Estrategia 1 (Directa para Video): CDN directo en el tag <video src="...">
    # ────────────────────────────────────────────────────────────────────────
    if is_video:
        # Bucle de Paciencia: Si la card de video aún está en render (Fases 1, 2 o 3),
        # esperar pacientemente en vez de quemar reintentos en falso.
        max_patience = 240
        p_start = time.monotonic()
        while time.monotonic() - p_start < max_patience:
            text = ""
            try:
                text = await card.inner_text()
            except Exception:
                pass

            # Si hay porcentaje (ej. 9%, 20%, 26%), el video sigue procesando en Flow
            pct_match = re.search(r'\b\d+%\b', text)
            if pct_match:
                pct = pct_match.group(0)
                elapsed = int(time.monotonic() - p_start)
                print(f"  [download] Video en render en Flow ({pct}, {elapsed}s). Esperando...")
                await asyncio.sleep(5.0)
                continue

            # Comprobar si el tag <video> ya tiene su enlace CDN firmado
            video_el = card.locator("video").first
            if await video_el.count() > 0:
                video_url = await video_el.get_attribute("src") or ""
                if not video_url:
                    video_url = await page.evaluate("(v) => v.currentSrc || v.src", video_el) or ""
                if (video_url.startswith("http://") or video_url.startswith("https://")) and len(video_url) > 40:
                    print(f"  [download] ¡Video terminado y listo en el reproductor! Procediendo...")
                    break
                elif video_url.startswith("blob:") and len(video_url) > 50:
                    print(f"  [download] ¡Video terminado con buffer blob listo! Procediendo...")
                    break

            # Despertar el reproductor de video de Flow: Flow requiere hover sobre la card
            # para inyectar el <video src="https://..."> (lazy loading).
            try:
                await card.hover(force=True)
                await page.evaluate("""(el) => {
                    if (!el) return;
                    el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    const v = el.querySelector('video') || el.querySelector('flow-video-tile');
                    if (v) {
                        v.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                        v.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    }
                }""", card)
            except Exception:
                pass

            # Si no hay porcentaje ni src, Flow está en el desenfoque inicial o en el revelado final
            elapsed = int(time.monotonic() - p_start)
            if elapsed > 15:
                more_btn = card.locator('button[aria-label*="opciones" i], button:has(:is(i, mat-icon):text-is("more_vert"))').first
                if await more_btn.count() > 0 and await more_btn.is_visible():
                    break

            print(f"  [download] Asentando render de video en Flow ({elapsed}s)...")
            await asyncio.sleep(3.0)

        video_el = card.locator("video").first
        if await video_el.count() > 0:
            video_url = await video_el.get_attribute("src")
            if not video_url:
                video_url = await page.evaluate("(v) => v.currentSrc || v.src", video_el)

            if video_url and (video_url.startswith("http://") or video_url.startswith("https://")):
                print(f"  [download] Enlace CDN directo detectado en <video src>. Descargando MP4...")
                try:
                    resp = await page.request.get(video_url, timeout=60_000)
                    if resp.ok:
                        body = await resp.body()
                        if len(body) >= 50_000:
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                            with open(output_path, "wb") as f:
                                f.write(body)
                            sz = Path(output_path).stat().st_size
                            print(f"  [download] OK: Video descargado exitosamente vía CDN directo en {output_path} ({sz} bytes).")
                            await asyncio.sleep(1.0)
                            return output_path
                except Exception as cdn_err:
                    print(f"  [download] Aviso: Descarga CDN directa lanzó ({cdn_err}); continuando con flujo UI...")

            elif video_url and video_url.startswith("blob:"):
                print(f"  [download] Enlace blob detectado en <video src>. Extrayendo buffer...")
                try:
                    import base64
                    blob_b64 = await page.evaluate("""async (url) => {
                        const res = await fetch(url);
                        const blob = await res.blob();
                        return new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                            reader.onerror = reject;
                            reader.readAsDataURL(blob);
                        });
                    }""", video_url)
                    if blob_b64:
                        data = base64.b64decode(blob_b64)
                        if len(data) >= 50_000:
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                            with open(output_path, "wb") as f:
                                f.write(data)
                            sz = Path(output_path).stat().st_size
                            print(f"  [download] OK: Video descargado exitosamente vía blob buffer en {output_path} ({sz} bytes).")
                            await asyncio.sleep(1.0)
                            return output_path
                except Exception as blob_err:
                    print(f"  [download] Aviso: Extracción blob lanzó ({blob_err}); continuando con flujo UI...")

    # ────────────────────────────────────────────────────────────────────────
    # Estrategia 2: Flujo UI interactivo (Menú 3 puntos -> Descargar -> Submenú)
    # ────────────────────────────────────────────────────────────────────────
    await _open_card_menu(page, card, is_video=is_video)

    dl_item = page.locator(_sel_menu_item("download")).first
    if await dl_item.count() == 0:
        dl_item = page.locator(SEL_DL_ITEM).first
    if await dl_item.count() == 0:
        await page.keyboard.press("Escape")
        raise RuntimeError("No encontré la opción 'Descargar' en el menú de la card.")

    candidatos = [SEL_DL_RES.get(resolution)] + [
        SEL_DL_RES[k] for k in SEL_DL_RES if k != resolution
    ]
    if is_video:
        candidatos.append('[role="menuitem"]:has-text("Tamaño original")')
    candidatos = [c for c in candidatos if c]

    # Desplegar el submenú de resoluciones con hover o click ANTES de esperar la descarga
    print("  [download 3/5] Desplegando submenú sobre 'Descargar'...")
    sub_visible = False
    try:
        await dl_item.hover(timeout=2_000)
        await asyncio.sleep(0.4)
        for sel in candidatos:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                sub_visible = True
                break
    except Exception:
        pass

    if not sub_visible:
        try:
            print("  [download 3/5] Hover no abrió submenú; haciendo clic en 'Descargar'...")
            await dl_item.click()
            await asyncio.sleep(0.4)
        except Exception:
            pass

    # Localizar la opción de resolución deseada
    target_loc = None
    elegido = None
    for sel in candidatos:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="visible", timeout=4_000)
            target_loc = loc
            elegido = sel
            print(f"  [download 4/5] Opción encontrada en submenú: {sel}")
            break
        except Exception:
            continue

    if not target_loc:
        print("  [download 4/5] Submenú no visible; se usará 'Descargar' directo.")
        target_loc = dl_item

    # Disparar la descarga dentro del listener oficial de Playwright
    print(f"  [download 5/5] Clic en la opción de descarga y esperando evento...")
    async with page.expect_download(timeout=60_000) as info:
        await target_loc.click()

    download = await info.value
    suggested = getattr(download, "suggested_filename", "archivo")
    print(f"  [download] Evento de descarga recibido ({suggested}). Guardando...")

    # Guardar en output_path
    saved = False

    # 1. Intentar download.path() directo si Playwright lo tiene en caché
    try:
        p = await download.path()
        if p and Path(p).exists() and Path(p).stat().st_size > 50_000:
            _save_to_dest(p, output_path)
            saved = True
            print(f"  [download] Guardado directo vía download.path() en {output_path}")
    except Exception:
        pass

    # 2. Intentar save_as de Playwright
    if not saved:
        temp_path = Path(f"{output_path}.download")
        try:
            await download.save_as(str(temp_path))
            _save_to_dest(temp_path, output_path)
            if Path(output_path).exists() and Path(output_path).stat().st_size > 50_000:
                saved = True
                print(f"  [download] OK: Guardado vía save_as en {output_path}")
        except Exception as err:
            print(f"  [download] Aviso: save_as lanzó ({err}); buscando archivo en disco...")
        finally:
            temp_path.unlink(missing_ok=True)

    # 3. Rescate por Filesystem (busca en carpeta de perfil y Downloads del usuario)
    if not saved:
        search_dirs = [
            Path(settings.FLOW_CHROME_PROFILE).parent / "downloads" if settings.FLOW_CHROME_PROFILE else Path("downloads"),
            Path.home() / "Downloads",
        ]
        for sec in range(25):
            for sdir in search_dirs:
                if not sdir.exists():
                    continue
                # Coincidencia exacta por nombre sugerido
                if suggested and (sdir / suggested).exists() and (sdir / suggested).stat().st_size > 50_000:
                    _save_to_dest(sdir / suggested, output_path)
                    saved = True
                    break
                # Búsqueda de archivos recién descargados (incluyendo .tmp de Playwright y .jpeg)
                recientes = sorted(
                    [f for f in sdir.iterdir() if f.is_file() and not f.name.endswith('.crdownload') and f.suffix.lower() in ('.tmp', '.jpeg', '.jpg', '.png', '.mp4', '.webp')],
                    key=lambda x: x.stat().st_mtime,
                    reverse=True
                )
                for cand in recientes[:6]:
                    if (time.time() - cand.stat().st_mtime) < 120 and cand.stat().st_size > 50_000:
                        try:
                            with open(cand, "rb") as cf:
                                header = cf.read(8)
                            # Validar que sea imagen (JPEG, PNG) o video (MP4/WebM)
                            if header.startswith(b'\xff\xd8') or header.startswith(b'\x89PNG') or header.startswith(b'RIFF') or header[4:8] == b'ftyp':
                                _save_to_dest(cand, output_path)
                                saved = True
                                print(f"  [download] Rescatado desde archivo temporal: {cand.name}")
                                break
                        except Exception:
                            pass
                if saved:
                    break
            if saved:
                break
            await asyncio.sleep(0.5)

    if not saved:
        raise RuntimeError(f"No se pudo guardar la descarga en {output_path}")

    sz = Path(output_path).stat().st_size if Path(output_path).exists() else 0
    print(f"  [download] OK: Lámina guardada con éxito en {output_path} ({sz} bytes).")

    # Asegurar que el contexto apunte de nuevo a la pestaña del proyecto Flow y cerrar about:blank
    try:
        from . import browser
        if browser._context:
            flow_pages = [p for p in browser._context.pages if not p.is_closed() and "/project/" in p.url]
            blank_pages = [p for p in browser._context.pages if not p.is_closed() and "about:blank" in p.url]
            if flow_pages and blank_pages:
                for bp in blank_pages:
                    try:
                        await bp.close()
                    except Exception:
                        pass
                browser._page = flow_pages[0]
                try:
                    await browser._page.bring_to_front()
                except Exception:
                    pass
    except Exception:
        pass

    # Pausa limpia en Python para asentar el navegador antes de la siguiente imagen
    await asyncio.sleep(1.5)
    return output_path


async def delete_latest_card(is_video: bool = False) -> None:
    """Borra el último resultado generado en caso de error (fallback) para reintentar.

    No fatal: si el menú cambió y no se puede borrar, se sigue adelante — perder
    la limpieza es molesto, tumbar el run por eso sería peor.
    """
    page = await get_page()

    card = page.locator(_sel_card(is_video)).first
    if await card.count() == 0:
        return

    print(f"  [cleanup] Intento fallido previo: limpiando card incompleta ({'video' if is_video else 'imagen'})...")
    try:
        if is_video:
            # En video, el clic derecho abre directamente el menú con "Borrar"
            await card.click(button="right", force=True)
            await asyncio.sleep(0.5)
            borrar_btn = page.locator(':is([role="menu"], [role="menuitem"], button):has-text("Borrar")').first
            if await borrar_btn.count() > 0 and await borrar_btn.is_visible():
                await borrar_btn.click()
                await page.wait_for_timeout(1_000)
                print("  [cleanup] OK: Card de video eliminada con éxito vía 'Borrar'.")
                return

        await _open_card_menu(page, card, is_video=is_video, caller="cleanup")
        del_item = page.locator(_sel_menu_item("delete")).first
        if await del_item.count() == 0:
            del_item = page.locator('[role="menuitem"]:has-text("Eliminar"), [role="menuitem"]:has-text("Borrar")').first
        if await del_item.count() > 0:
            await del_item.click()
            await page.wait_for_timeout(1_000)
            print("  [cleanup] OK: Card eliminada con éxito.")
        else:
            await page.keyboard.press("Escape")
    except Exception as e:
        print(f"  [cleanup] Aviso: No se pudo eliminar la card ({e}). Continuando.")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
