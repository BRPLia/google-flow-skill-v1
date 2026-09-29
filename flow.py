#!/usr/bin/env python
"""
flow.py - CLI para manejar Google Flow (labs.google) con Playwright.

Esta es la UNICA puerta de entrada. Un agente de IA NO necesita escribir
codigo de Playwright: solo llama a estos comandos.

Comandos
--------
  python flow.py login
      Abre el navegador para loguearte en Google con tu cuenta. La sesion
      queda guardada de forma PERMANENTE en session/flowbot-profile.
      Solo se hace una vez (o cuando caduque la sesion).

  python flow.py status
      Dice si ya hay sesion guardada.

  python flow.py image --prompt "..." [--ratio 9:16] [--model "Nano Banana 2 Lite"]
                        [--image referencia.png] [--name escena1] [--out outputs]
      Genera UNA imagen (texto->imagen, o imagen+prompt->imagen si das --image).

  python flow.py video --prompt "..." [--ratio 9:16] [--model "Veo 3.1 - Lite"]
                        [--duration 8s]
                        [--start frame.png] [--end frame_final.png]
                        [--name escena1] [--out outputs]
      Genera UN video. Sin --start = texto->video. Con --start = anima esa
      imagen. Con --start y --end = interpola inicio->fin.

  python flow.py batch guion.json [--out outputs]
      Ejecuta una lista de trabajos EN ORDEN dentro de UN solo proyecto Flow.
      Ver examples/guion_ejemplo.json para el formato.

Modelos validos
---------------
  Imagen: "Nano Banana 2 Lite", "Nano Banana 2", "Nano Banana Pro", "Imagen 4"
  Video : "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality", "Omni 1.1 Flash"
  Ratios: "9:16", "16:9", "1:1", "4:3", "3:4"
"""
import argparse
import asyncio
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import flow_provider as flow
from flow_provider import settings

# Consola UTF-8 en Windows (acentos/emojis sin romper la salida).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_OUT = BASE_DIR / "outputs"
FLOW_URL = "https://labs.google/fx/es-419/tools/flow"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in ("_", "-", ".")) or _stamp()


def _out_path(out_dir: Path, name: str, ext: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / f"{_safe(name)}.{ext}")


def _resolve_asset(project_dir: Path, ref: str | None) -> str | None:
    """Resuelve una referencia a un asset (start/end/image) dentro del batch.

    Si 'ref' existe tal cual, se usa. Si no, se busca por nombre dentro de la
    carpeta del proyecto (con o sin .png). Asi el guion puede encadenar solo
    con el 'name' de un job anterior, sin rutas largas.
    """
    if not ref:
        return ref
    p = Path(ref)
    if p.exists():
        return str(p)
    cand = project_dir / p.name
    if cand.exists():
        return str(cand)
    if not cand.suffix:
        cand_png = project_dir / f"{p.name}.png"
        if cand_png.exists():
            return str(cand_png)
    return ref  # se deja igual; fallara con error claro si no existe


def session_exists() -> bool:
    profile = Path(settings.FLOW_CHROME_PROFILE)
    return profile.exists() and any(profile.iterdir())


# ---------------------------------------------------------------------------
# login / status
# ---------------------------------------------------------------------------
async def cmd_login(_args) -> int:
    profile = Path(settings.FLOW_CHROME_PROFILE)
    profile.mkdir(parents=True, exist_ok=True)
    print("=== LOGIN GOOGLE FLOW ===")
    print(f"Perfil persistente: {profile}")
    print("Se abrira Chrome. Inicia sesion con tu cuenta de Google.")
    print("Cuando aparezca el botón de proyecto nuevo, el script guarda y cierra solo.")
    print()

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(FLOW_URL)

        # Poll hasta detectar que ya estamos dentro de Flow logueados.
        logged = False
        for i in range(80):  # ~240s
            await page.wait_for_timeout(3000)
            url = page.url
            try:
                ready = await page.get_by_role(
                    "button", name=re.compile(r"Proyecto nuevo|Nuevo proyecto|New project", re.I)
                ).count() > 0
            except Exception:
                ready = False
            if ready and "accounts.google" not in url:
                logged = True
                print("  -> Sesion detectada. Guardando...")
                await page.wait_for_timeout(3000)
                break
            if i % 5 == 0:
                print(f"  esperando login... ({url})")

        await ctx.close()

    if logged:
        print("OK: sesion guardada. Ya puedes generar imagenes/videos.")
        return 0
    print("AVISO: no se detecto login. Vuelve a correr 'python flow.py login'.")
    return 1


async def cmd_status(_args) -> int:
    if session_exists():
        print(f"OK: sesion presente en {settings.FLOW_CHROME_PROFILE}")
        return 0
    print("SIN SESION. Corre primero: python flow.py login")
    return 1


# ---------------------------------------------------------------------------
# Generadores atomicos (asumen proyecto YA abierto)
# ---------------------------------------------------------------------------
async def _gen_image(prompt, ratio, model, count, image, out_path) -> str:
    if count != 1:
        raise ValueError("Esta CLI descarga una imagen por trabajo. Para un lote, usa varios jobs image con count=1.")
    await flow.select_image_mode(aspect_ratio=ratio, count=count, model=model)
    if image:
        await flow.upload_standalone_image(image)
    pre = await flow.get_canvas_count()
    await flow.submit_prompt(prompt)
    await flow.wait_for_image(pre_submit_count=pre)
    return await flow.download_latest(out_path, resolution="1K", is_video=False)


async def _gen_video(prompt, ratio, model, count, start, end, out_path, duration=None) -> str:
    if count != 1:
        raise ValueError("Esta CLI descarga un video por trabajo. Para un lote, usa varios jobs video con count=1.")
    if start and end:
        await flow.select_video_mode(mode="fotogramas", model=model, aspect_ratio=ratio, count=count, duration=duration)
        await flow.upload_frame(start, slot="initial")
        await asyncio.sleep(3)
        await flow.upload_frame(end, slot="final")
    elif start:
        await flow.select_video_mode(mode="fotogramas", model=model, aspect_ratio=ratio, count=count, duration=duration)
        await flow.upload_frame(start, slot="initial")
    else:
        await flow.select_video_mode(mode="texto", model=model, aspect_ratio=ratio, count=count, duration=duration)
    pre = await flow.get_canvas_count()
    await flow.submit_prompt(prompt)
    await flow.wait_for_video(pre_submit_count=pre)
    return await flow.download_latest(out_path, resolution="720p", is_video=True)


# ---------------------------------------------------------------------------
# Comandos de generacion
# ---------------------------------------------------------------------------
async def cmd_image(args) -> int:
    if not session_exists():
        print("SIN SESION. Corre primero: python flow.py login")
        return 1
    out_dir = Path(args.out)
    name = args.name or f"imagen_{_stamp()}"
    out_path = _out_path(out_dir, name, "png")
    await flow.startup()
    try:
        await flow.create_project()
        saved = await _gen_image(args.prompt, args.ratio, args.model, args.count, args.image, out_path)
        print(f"OK imagen -> {saved}")
        return 0
    finally:
        await flow.shutdown()


async def cmd_video(args) -> int:
    if not session_exists():
        print("SIN SESION. Corre primero: python flow.py login")
        return 1
    out_dir = Path(args.out)
    name = args.name or f"video_{_stamp()}"
    out_path = _out_path(out_dir, name, "mp4")
    await flow.startup()
    try:
        await flow.create_project()
        saved = await _gen_video(args.prompt, args.ratio, args.model, args.count, args.start, args.end, out_path, args.duration)
        print(f"OK video -> {saved}")
        return 0
    finally:
        await flow.shutdown()


async def cmd_batch(args) -> int:
    if not session_exists():
        print("SIN SESION. Corre primero: python flow.py login")
        return 1

    data = json.loads(Path(args.jobfile).read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    d_ratio = defaults.get("ratio", "9:16")
    d_img_model = defaults.get("image_model", "Nano Banana 2 Lite")
    d_vid_model = defaults.get("video_model", "Veo 3.1 - Lite")
    d_vid_duration = defaults.get("video_duration")
    jobs = data.get("jobs", [])

    # Cada proyecto va a su propia subcarpeta: facil de revisar y de borrar.
    project = data.get("project") or f"proyecto_{_stamp()}"
    project_dir = Path(args.out) / _safe(project)
    project_dir.mkdir(parents=True, exist_ok=True)

    print(f"BATCH '{project}': {len(jobs)} trabajos. Salida -> {project_dir}")
    results = []
    await flow.startup()
    try:
        await flow.create_project()
        for i, job in enumerate(jobs, 1):
            jtype = job.get("type", "image")
            name = job.get("name") or f"{jtype}_{i:02d}"
            prompt = job.get("prompt", "")
            ratio = job.get("ratio", d_ratio)
            print(f"\n--- [{i}/{len(jobs)}] {jtype} :: {name} ---")
            try:
                if jtype == "image":
                    out_path = _out_path(project_dir, name, "png")
                    saved = await _gen_image(
                        prompt, ratio, job.get("model", d_img_model),
                        int(job.get("count", 1)),
                        _resolve_asset(project_dir, job.get("image")), out_path,
                    )
                elif jtype == "video":
                    out_path = _out_path(project_dir, name, "mp4")
                    saved = await _gen_video(
                        prompt, ratio, job.get("model", d_vid_model),
                        int(job.get("count", 1)),
                        _resolve_asset(project_dir, job.get("start")),
                        _resolve_asset(project_dir, job.get("end")), out_path,
                        job.get("duration", d_vid_duration),
                    )
                else:
                    print(f"  tipo desconocido '{jtype}', saltando.")
                    continue
                print(f"  OK -> {saved}")
                results.append({"name": name, "type": jtype, "file": saved, "ok": True})
            except Exception as e:
                print(f"  ERROR en '{name}': {e}")
                debug_dir = project_dir / "_debug"
                try:
                    debug_dir.mkdir(exist_ok=True)
                    page = await flow.get_page()
                    debug_name = f"{i:02d}_{_safe(name)}"
                    await page.screenshot(path=str(debug_dir / f"{debug_name}.png"))
                    (debug_dir / f"{debug_name}.html").write_text(await page.content(), encoding="utf-8")
                    print(f"  Diagnóstico guardado en {debug_dir}")
                except Exception as debug_error:
                    print(f"  No se pudo guardar el diagnóstico: {debug_error}")
                results.append({"name": name, "type": jtype, "ok": False, "error": str(e)})
    finally:
        await flow.shutdown()

    report = project_dir / "batch_report.json"
    report.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\nBATCH terminado: {ok}/{len(results)} OK. Carpeta: {project_dir}")
    return 0 if ok == len(results) else 1


async def cmd_clean(args) -> int:
    out_dir = Path(args.out)
    if args.project:
        target = out_dir / _safe(args.project)
        if not target.exists():
            print(f"No existe: {target}")
            return 0
        shutil.rmtree(target)
        print(f"Borrado proyecto: {target}")
        return 0
    if not out_dir.exists():
        print(f"Nada que limpiar en {out_dir}")
        return 0
    borrados = 0
    for child in out_dir.iterdir():
        if child.name == "LEEME.txt":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        borrados += 1
    print(f"Limpiado {out_dir}: {borrados} elementos borrados.")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CLI Google Flow (Playwright).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Loguearse en Google Flow (una vez).")
    sub.add_parser("status", help="Ver si hay sesion guardada.")

    pi = sub.add_parser("image", help="Generar una imagen.")
    pi.add_argument("--prompt", required=True)
    pi.add_argument("--ratio", default="9:16")
    pi.add_argument("--model", default="Nano Banana 2 Lite")
    pi.add_argument("--count", type=int, default=1)
    pi.add_argument("--image", default=None, help="Imagen de referencia para editar.")
    pi.add_argument("--name", default=None)
    pi.add_argument("--out", default=str(DEFAULT_OUT))

    pv = sub.add_parser("video", help="Generar un video.")
    pv.add_argument("--prompt", required=True)
    pv.add_argument("--ratio", default="9:16")
    pv.add_argument("--model", default="Veo 3.1 - Lite")
    pv.add_argument("--count", type=int, default=1)
    pv.add_argument("--duration", default=None, help="Duracion del clip, por ejemplo 8s (si el modelo la admite).")
    pv.add_argument("--start", default=None, help="Fotograma inicial (imagen).")
    pv.add_argument("--end", default=None, help="Fotograma final (imagen).")
    pv.add_argument("--name", default=None)
    pv.add_argument("--out", default=str(DEFAULT_OUT))

    pb = sub.add_parser("batch", help="Ejecutar guion JSON de varios trabajos.")
    pb.add_argument("jobfile")
    pb.add_argument("--out", default=str(DEFAULT_OUT))

    pc = sub.add_parser("clean", help="Borrar resultados de outputs.")
    pc.add_argument("project", nargs="?", default=None,
                    help="Nombre del proyecto a borrar. Vacio = limpiar todo outputs.")
    pc.add_argument("--out", default=str(DEFAULT_OUT))

    return p


HANDLERS = {
    "login": cmd_login,
    "status": cmd_status,
    "image": cmd_image,
    "video": cmd_video,
    "batch": cmd_batch,
    "clean": cmd_clean,
}


# ---------------------------------------------------------------------------
# :)
# ---------------------------------------------------------------------------
EASTER_EGG = r"""
   _   _ _   _ ____   ___
  | \ | | | | |  _ \ / _ \
  |  \| | | | | |_) | | | |
  | |\  | |_| |  _ <| |_| |
  |_| \_|\___/|_| \_\\___/     x   B R P L

  Google Flow Skill -- forjado por NURO para BRPL.
  El contexto es el verdadero superpoder. Disfruta y crea.
"""


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] in ("nuro", "brpl", "--credits"):
        print(EASTER_EGG)
        return 0
    args = build_parser().parse_args()
    return asyncio.run(HANDLERS[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
