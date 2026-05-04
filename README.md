# Servientrega Tracker

Microservicio FastAPI + Playwright para extraer estado de guías Servientrega.

## Deploy en Render

1. Sube esta carpeta a un repo de GitHub (puede ser privado).
2. Entra a https://dashboard.render.com → **New +** → **Web Service**.
3. Conecta el repo. Render detecta el `Dockerfile` automáticamente.
4. Configura:
   - **Runtime**: Docker
   - **Plan**: Starter ($7/mes — necesario porque Playwright requiere ~1GB RAM)
   - **Region**: Oregon o la más cercana
5. En **Environment** agrega:
   - `API_TOKEN` = un string aleatorio largo (ej: genera uno con `openssl rand -hex 32`)
6. **Create Web Service**. El primer build tarda ~5-8 min.

Cuando termine, tendrás una URL tipo `https://servientrega-tracker-xxxx.onrender.com`.

## Test rápido

```bash
curl -H "Authorization: Bearer TU_TOKEN" \
  https://tu-servicio.onrender.com/track/2150029920176
```

## Endpoints

- `GET /` — health check
- `GET /track/{guia}` — rastrea una guía
- `POST /track-batch` body `{"guias": ["123", "456"]}` — máx 25, procesa de a 3 en paralelo

Todos los endpoints (excepto `/`) requieren header `Authorization: Bearer <API_TOKEN>`.

## Siguiente paso

Pásame:
1. La **URL pública** de Render
2. El **API_TOKEN** que configuraste

Y actualizo el edge function `track-guia` para usar este servicio en lugar de Firecrawl.
