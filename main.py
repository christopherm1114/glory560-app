"""
main.py
-------
El punto de entrada de la aplicación web (FastAPI).

Aquí se definen las "rutas" (URLs) que expone el servidor:
  GET  /                            -> comprobar que la app está viva
  GET  /salud                       -> lo mismo, pero en texto plano (keep-alive)
  POST /webhook/telegram            -> Telegram nos envía aquí cada mensaje
  GET/POST /tasks/revisar-vencimientos -> disparar los recordatorios diarios

Render ejecuta esta app con:  uvicorn main:app --host 0.0.0.0 --port $PORT

REGLA DE ORO DE ESTE ARCHIVO: ninguna ruta debe tardar en responder.
El plan gratuito de Render duerme el servicio tras 15 minutos sin tráfico y
el arranque en frío tarda casi un minuto; por eso hay un endpoint de salud
barato (/salud) que el cron puede golpear cada 10 minutos sin costo alguno.
Y tanto el webhook como la tarea contestan de inmediato y hacen el trabajo
después, para que ni Telegram ni cron-job.org se queden esperando.
"""

from fastapi import BackgroundTasks, FastAPI, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse

from config import TASKS_TOKEN, TELEGRAM_WEBHOOK_SECRET
import handlers, tareas
import web

app = FastAPI(title="Control de Mantenimientos Glory 560")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    """
    Añade las cabeceras de seguridad que el navegador necesita para defender
    al usuario. Sin ellas el panel se podía incrustar en una página ajena
    (clickjacking) y no había nada que limitara la ejecución de scripts.

    La CSP es la más importante: aunque se escape todo lo que se pinta, es la
    red que atrapa cualquier inyección que se escape en el futuro. El
    'unsafe-inline' es necesario porque panel.html lleva su CSS y su
    JavaScript dentro del propio archivo; el día que se separen en archivos
    aparte hay que quitarlo, y solo entonces la CSP protegerá de verdad.
    """
    respuesta = await call_next(request)
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    respuesta.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    respuesta.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        # Chart.js se sirve desde este CDN; ninguna otra fuente está permitida.
        "script-src 'self' https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        # Las seis imágenes del panel van incrustadas como data: URI.
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )
    return respuesta


# Rutas de la web (/panel, /api/login, /api/mis-datos, /api/usuarios, ...).
app.include_router(web.router)


@app.get("/")
def salud():
    """Ruta simple para verificar que el servicio está funcionando."""
    return {"status": "ok", "app": "Glory 560 Mantenimientos"}


@app.get("/salud", response_class=PlainTextResponse)
@app.head("/salud")
def salud_texto():
    """
    Keep-alive para cron-job.org. No toca la base de datos ni envía nada:
    solo demuestra que el proceso está vivo, para que Render no lo duerma.
    Es DELIBERADAMENTE distinto de /tasks/revisar-vencimientos: mezclar las
    dos cosas obligaba a elegir entre un servidor dormido o un usuario
    recibiendo recordatorios cada diez minutos.
    """
    return PlainTextResponse("ok")


@app.post("/webhook/telegram")
async def webhook_telegram(
    request: Request,
    tareas_fondo: BackgroundTasks,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """
    Telegram llama a esta ruta cada vez que llega un mensaje al bot.
    Primero verificamos el secreto (para asegurar que viene de Telegram).

    Respondemos 200 ANTES de procesar el mensaje. Telegram reenvía el mismo
    update si no recibe respuesta pronto, y en un arranque en frío eso pasaba:
    el usuario recibía la respuesta duplicada o se le registraba dos veces el
    mismo mantenimiento. El trabajo real corre en segundo plano.
    """
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Secreto inválido")

    update = await request.json()

    # handlers.procesar_update es SÍNCRONO; al registrarlo como tarea de fondo,
    # Starlette lo ejecuta en un hilo aparte y no bloquea el bucle asíncrono.
    tareas_fondo.add_task(handlers.procesar_update, update)

    # Telegram solo necesita un 200 OK; el contenido no importa.
    return {"ok": True}


# Acepta GET y POST para que cualquier programador externo (ej. cron-job.org)
# pueda llamarlo fácilmente. Se protege con TASKS_TOKEN, que puede venir en la
# dirección (?token=...) o, mejor, en la cabecera X-Tasks-Token.
@app.get("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
@app.post("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
def revisar_vencimientos(
    tareas_fondo: BackgroundTasks,
    token: str = "",
    x_tasks_token: str = Header(default=""),
):
    # SIEMPRE devolvemos una respuesta minúscula en texto plano.
    # cron-job.org (plan gratis) corta las respuestas grandes y aborta la
    # petición a los ~30 segundos, marcando el job como fallido; tras varios
    # fallos lo desactiva solo. Por eso contestamos ya y enviamos después.
    entregado = x_tasks_token or token
    if TASKS_TOKEN and entregado != TASKS_TOKEN:
        return PlainTextResponse("token invalido", status_code=403)

    tareas_fondo.add_task(tareas.ejecutar_revision)
    return PlainTextResponse("ok")
