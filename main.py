"""
Servientrega Tracker - FastAPI microservice
Usa Playwright (Chromium headless) para extraer estado de guías.
"""
import os
import re
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from playwright.async_api import async_playwright

API_TOKEN = os.getenv("API_TOKEN", "change-me")
TRACK_URL = "https://www.servientrega.com/wps/portal/rastreo-envio?codigo={guia}"

app = FastAPI(title="Servientrega Tracker", version="1.0.0")


def auth(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    if authorization.split(" ", 1)[1] != API_TOKEN:
        raise HTTPException(401, "Invalid token")
    return True


class TrackResult(BaseModel):
    guia: str
    ok: bool
    estado: str = ""
    origen: str = ""
    destino: str = ""
    raw: str = ""
    error: Optional[str] = None


class BatchRequest(BaseModel):
    guias: List[str]


def parse(text: str) -> dict:
    out = {"estado": "", "origen": "", "destino": ""}
    if not text:
        return out
    # Estado
    m = re.search(r"(entregad[oa]|en\s*tr[áa]nsito|en\s*reparto|devuelt[oa]|novedad|recibid[oa]|generad[oa])[^\n\r.]{0,80}", text, re.I)
    if m:
        out["estado"] = m.group(0).strip()[:200]
    m = re.search(r"origen[:\s-]+([^\n\r]{2,80})", text, re.I)
    if m:
        out["origen"] = m.group(1).strip()
    m = re.search(r"destino[:\s-]+([^\n\r]{2,80})", text, re.I)
    if m:
        out["destino"] = m.group(1).strip()
    return out


async def track_one(browser, guia: str) -> TrackResult:
    ctx = await browser.new_context()
    page = await ctx.new_page()
    try:
        await page.goto(TRACK_URL.format(guia=guia), wait_until="domcontentloaded", timeout=45000)
        # Esperar a que cargue contenido dinámico
        try:
            await page.wait_for_selector("text=/origen|destino|estado|entregad/i", timeout=20000)
        except Exception:
            await page.wait_for_timeout(5000)
        text = await page.inner_text("body")
        parsed = parse(text)
        ok = bool(parsed["estado"] or parsed["origen"] or parsed["destino"])
        return TrackResult(guia=guia, ok=ok, **parsed, raw=text[:4000])
    except Exception as e:
        return TrackResult(guia=guia, ok=False, error=str(e))
    finally:
        await ctx.close()


@app.get("/")
def health():
    return {"status": "ok", "service": "servientrega-tracker"}


@app.get("/track/{guia}", response_model=TrackResult, dependencies=[Depends(auth)])
async def track(guia: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            return await track_one(browser, guia)
        finally:
            await browser.close()


@app.post("/track-batch", response_model=List[TrackResult], dependencies=[Depends(auth)])
async def track_batch(req: BatchRequest):
    if len(req.guias) > 25:
        raise HTTPException(400, "Max 25 guías por batch")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            # Procesar de a 3 en paralelo para no saturar
            results: List[TrackResult] = []
            sem = asyncio.Semaphore(3)
            async def run(g):
                async with sem:
                    return await track_one(browser, g)
            results = await asyncio.gather(*[run(g) for g in req.guias])
            return results
        finally:
            await browser.close()
