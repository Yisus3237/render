"""
Servientrega Tracker - microservicio FastAPI + Playwright
Despliegue en Render. Auth Bearer token (env API_TOKEN).
"""
import os
import re
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from playwright.async_api import async_playwright

API_TOKEN = os.getenv("API_TOKEN", "")
TRACK_URL = "https://misservicios.servientrega.com/Tracking/?GuiaABuscar={guia}&Tipo=GUIA"
NAV_TIMEOUT = 45000  # 45s
WAIT_TIMEOUT = 25000  # 25s

app = FastAPI(title="servientrega-tracker")


def _check_auth(authorization: Optional[str]):
    if not API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.split(" ", 1)[1].strip() != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/")
async def health():
    return {"status": "ok", "service": "servientrega-tracker"}


class BatchBody(BaseModel):
    guias: List[str]


def _parse(text: str):
    """Extrae estado / origen / destino del texto renderizado."""
    t = re.sub(r"[ \t]+", " ", text)
    estado = origen = destino = ""

    # Estado: busca patrones "Estado: XXX" o líneas tipo "ENTREGADO", "EN REPARTO", etc.
    m = re.search(r"Estado(?:\s+actual)?\s*[:\-]\s*([^\n\r]+)", t, re.I)
    if m:
        estado = m.group(1).strip()
    if not estado:
        # palabras clave típicas
        for kw in ["ENTREGADO", "EN REPARTO", "EN BODEGA", "EN TRÁNSITO", "EN TRANSITO",
                   "DEVUELTO", "NOVEDAD", "RECOGIDO", "ANULADO", "PENDIENTE"]:
            if re.search(rf"\b{kw}\b", t, re.I):
                estado = kw.title()
                break

    m = re.search(r"Origen\s*[:\-]\s*([^\n\r]+)", t, re.I)
    if m:
        origen = m.group(1).strip()
    m = re.search(r"Destino\s*[:\-]\s*([^\n\r]+)", t, re.I)
    if m:
        destino = m.group(1).strip()

    return estado, origen, destino


async def _track_one(browser, guia: str):
    ctx = await browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
        viewport={"width": 1280, "height": 900},
    )
    page = await ctx.new_page()
    try:
        url = TRACK_URL.format(guia=guia)
        await page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        # Espera a que aparezca contenido real del tracking. Probamos varios selectores.
        try:
            await page.wait_for_selector(
                "table, .tracking, #divResultado, text=/estado|origen|destino|entregad/i",
                timeout=WAIT_TIMEOUT,
            )
        except Exception:
            pass
        # da tiempo extra para que renderice JS
        await page.wait_for_timeout(2500)
        # asegúrate de que ${loading} ya no esté presente
        for _ in range(8):
            html = await page.content()
            if "${loading}" not in html and "${" not in html:
                break
            await page.wait_for_timeout(1000)

        text = await page.inner_text("body")
        estado, origen, destino = _parse(text)
        return {
            "guia": guia,
            "ok": bool(estado),
            "estado": estado,
            "origen": origen,
            "destino": destino,
            "raw": text[:8000],
            "error": None,
        }
    except Exception as e:
        return {"guia": guia, "ok": False, "estado": "", "origen": "", "destino": "",
                "raw": "", "error": str(e)}
    finally:
        await ctx.close()


@app.get("/track/{guia}")
async def track(guia: str, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            return await _track_one(browser, guia)
        finally:
            await browser.close()


@app.post("/track-batch")
async def track_batch(body: BatchBody, authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    guias = [g for g in body.guias if g][:25]
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            sem = asyncio.Semaphore(2)

            async def run(g):
                async with sem:
                    return await _track_one(browser, g)

            return {"results": await asyncio.gather(*[run(g) for g in guias])}
        finally:
            await browser.close()
