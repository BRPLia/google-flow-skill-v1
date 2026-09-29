"""
Lifecycle del browser Playwright para Google Flow.
startup() → llamado desde FastAPI lifespan al arrancar.
shutdown() → llamado desde FastAPI lifespan al cerrar.
"""
import asyncio
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from . import settings

_playwright: Playwright | None = None
_context: BrowserContext | None = None
_page: Page | None = None
SEL_SETTINGS_TRIGGER = 'button[aria-label="Botón de configuración"], button[aria-label="Activador de ajustes"]'
_lock = asyncio.Lock()
_last_project_url: str | None = None


async def startup() -> None:
    global _playwright, _context, _page
    _playwright = await async_playwright().start()

    session_file = settings.FLOW_SESSION_FILE
    use_session = bool(session_file and Path(session_file).exists())

    if use_session:
        browser = await _playwright.chromium.launch(
            headless=settings.FLOW_HEADLESS,
            channel="chrome",
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        _context = await browser.new_context(
            storage_state=session_file,
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
        )
    else:
        # Limpieza preventiva de archivos de bloqueo (locks) de Chrome antes de arrancar
        profile_path = settings.FLOW_CHROME_PROFILE
        if profile_path:
            p_dir = Path(profile_path)
            if p_dir.exists():
                for lock_name in ["SingletonLock", "lock", "Lock"]:
                    lock_file = p_dir / lock_name
                    if lock_file.exists():
                        try:
                            # En Windows a veces SingletonLock es un archivo, en Unix es un symlink
                            lock_file.unlink(missing_ok=True)
                        except Exception:
                            # Ignorar si no se puede borrar porque está en uso real
                            pass
                            
        profile_dir = Path(settings.FLOW_CHROME_PROFILE) if settings.FLOW_CHROME_PROFILE else Path("/tmp/flow-profile")
        dl_dir = profile_dir.parent / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=settings.FLOW_HEADLESS,
            channel="chrome",
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            accept_downloads=True,
            downloads_path=str(dl_dir),
            viewport={"width": 1280, "height": 900},
        )

    _page = _context.pages[0] if _context.pages else await _context.new_page()


async def shutdown() -> None:
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _playwright = _context = _page = None


def _remember_project(page) -> None:
    """Conservar el proyecto real; no depende del output_dir de cada motor."""
    global _last_project_url
    if page is None:
        return
    parsed = urlsplit(page.url)
    if parsed.scheme == "https" and parsed.hostname in ("flow.google.com", "labs.google") and "/project/" in parsed.path:
        _last_project_url = page.url


async def _restore_project(page) -> None:
    if not _last_project_url:
        raise RuntimeError("Chrome se cerró y no hay un proyecto Flow registrado para reanudar.")
    await page.goto(_last_project_url, wait_until="domcontentloaded", timeout=60_000)
    await page.locator(SEL_SETTINGS_TRIGGER).wait_for(state="visible", timeout=45_000)
    print(f"  [flow-browser] Proyecto restaurado: {page.url}")


async def get_page() -> Page:
    global _page, _context
    # La URL sigue disponible en el objeto Page aunque su ventana se haya cerrado.
    _remember_project(_page)
    if _context is None:
        await startup()
    try:
        project_pages = [p for p in _context.pages if not p.is_closed() and "/project/" in p.url]
        if project_pages:
            _page = project_pages[0]
        elif _page is None or _page.is_closed():
            active = [p for p in _context.pages if not p.is_closed()]
            _page = active[0] if active else await _context.new_page()
        await _page.evaluate("() => true")
    except Exception as err:
        print(f"  [flow-browser] Sesión o página cerrada ({err}). Reanudando proyecto Flow...")
        try:
            await shutdown()
        except Exception:
            pass
        await startup()
        # Propagar el error si la restauración falla, nunca devolver about:blank.
        await _restore_project(_page)
    else:
        if _last_project_url and _page.url == "about:blank":
            await _restore_project(_page)
    _remember_project(_page)
    return _page


def get_lock() -> asyncio.Lock:
    return _lock
