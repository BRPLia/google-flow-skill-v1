"""
Creación y navegación de proyectos en Google Flow.
"""
from .browser import get_page, SEL_SETTINGS_TRIGGER

FLOW_BASE_URL = "https://labs.google/fx/es-419/tools/flow"


import re

async def _dismiss_fullscreen_viewer(page) -> None:
    """Presiona Escape para cerrar cualquier visor/lightbox que se haya abierto accidentalmente."""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(1000)
    except Exception:
        pass


PANEL_OVERLAY = '[role="dialog"], [aria-modal="true"]'


async def _await_user_dismisses_panel(page, seconds: int = 15) -> None:
    """Si Flow muestra un panel de novedades o anuncio encima de la interfaz,
    avisa y da unos segundos para que el usuario lo cierre a mano en la ventana.

    No se cierra automáticamente: el diseño del panel cambia cada vez y su botón
    ('Comenzar', 'Entendido', una X...) no es predecible. Si sigue abierto al
    vencer el plazo continúa igual — esto nunca aborta la corrida."""
    panel = page.locator(PANEL_OVERLAY).first
    try:
        await panel.wait_for(state="visible", timeout=3_000)
    except Exception:
        return  # No apareció: entrada normal.

    print("\n>>> Google Flow muestra un panel o anuncio sobre la interfaz.")
    print(f">>> Ciérralo en la ventana de Chrome. Espero {seconds}s y sigo igual.\n")
    try:
        await panel.wait_for(state="hidden", timeout=seconds * 1_000)
        print(">>> Panel cerrado. Continuando.\n")
    except Exception:
        print(">>> El panel sigue abierto. Continuando de todas formas.\n")
    await page.wait_for_timeout(1_500)


async def ensure_all_media_tab(page) -> None:
    """Asegura que el panel lateral izquierdo esté en 'Todo el contenido multimedia'.
    
    Debe llamarse antes de cualquier operación que necesite encontrar
    imágenes o videos en el canvas principal del proyecto.
    """
    try:
        # El botón tiene un ícono google-symbols "dashboard" y el texto accesible oculto
        all_media_btn = page.locator('button:has(i:text-is("dashboard"))')
        
        if await all_media_btn.count() > 0 and await all_media_btn.first.is_visible():
            await all_media_btn.first.click()
            await page.wait_for_timeout(1500)
    except Exception:
        pass


async def create_project() -> tuple[str, str]:
    """Crea un proyecto nuevo en Flow. Retorna (project_uuid, project_url).
    Debe llamarse mientras se sostiene get_lock().
    """
    page = await get_page()
    await page.goto(FLOW_BASE_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    await _await_user_dismisses_panel(page)

    # Click en Proyecto nuevo
    await page.wait_for_selector('button:has-text("Proyecto nuevo")', timeout=45000)
    new_btn = page.locator('button:has-text("Proyecto nuevo")')
    await new_btn.first.click()

    # Esperar URL de proyecto
    await page.wait_for_url("**/project/**", timeout=15000)
    project_url = page.url
    project_uuid = project_url.rstrip("/").split("/")[-1]

    # Esperar SPA render — CRÍTICO sin esto pantalla negra
    await page.wait_for_timeout(5000)
    await page.wait_for_selector(SEL_SETTINGS_TRIGGER, timeout=45000)

    await _dismiss_fullscreen_viewer(page)
    await ensure_all_media_tab(page)
    return project_uuid, project_url


async def navigate_to_project(project_uuid: str) -> None:
    """Navega a un proyecto existente. Debe llamarse con lock."""
    page = await get_page()
    if f"/project/{project_uuid}" not in page.url:
        target_url = f"https://flow.google.com/project/{project_uuid}"
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await _await_user_dismisses_panel(page)
        await page.wait_for_selector(SEL_SETTINGS_TRIGGER, timeout=45000)

    # Siempre al entrar al proyecto: cerrar visores accidentales y asegurar pestaña correcta
    await _dismiss_fullscreen_viewer(page)
    await ensure_all_media_tab(page)

