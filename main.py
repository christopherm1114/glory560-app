"""
main.py
-------
El punto de entrada de la aplicación web (FastAPI).

Aquí se definen las "rutas" (URLs) que expone el servidor:
  GET  /                        -> comprobar que la app está viva
  POST /webhook/telegram        -> Telegram nos envía aquí cada mensaje
  POST /tasks/revisar-vencimientos -> disparar recordatorios manualmente

Render ejecuta esta app con:  uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from config import TELEGRAM_WEBHOOK_SECRET
import handlers, tareas
import web

app = FastAPI(title="Control de Mantenimientos Glory 560")

# Rutas de la web (/panel, /api/login, /api/mis-datos, /api/usuarios, ...).
app.include_router(web.router)


@app.get("/")
def salud():
    """Ruta simple para verificar que el servicio está funcionando."""
    return {"status": "ok", "app": "Glory 560 Mantenimientos"}


@app.post("/webhook/telegram")
async def webhook_telegram(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """
    Telegram llama a esta ruta cada vez que llega un mensaje al bot.
    Primero verificamos el secreto (para asegurar que viene de Telegram).
    """
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Secreto inválido")

    update = await request.json()

    # Nuestro código de handlers es SÍNCRONO (usa la base de datos de forma
    # normal). Para no bloquear el servidor, lo corremos en un hilo aparte.
    await run_in_threadpool(handlers.procesar_update, update)

    # Telegram solo necesita un 200 OK; el contenido no importa.
    return {"ok": True}


# Acepta GET y POST para que cualquier programador externo (ej. cron-job.org)
# pueda llamarlo fácilmente. Se protege con un 'token' en la dirección, que
# debe coincidir con TELEGRAM_WEBHOOK_SECRET (así nadie más puede dispararlo).
@app.get("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
@app.post("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
async def revisar_vencimientos(token: str = ""):
    # SIEMPRE devolvemos una respuesta minúscula en texto plano.
    # cron-job.org (plan gratis) corta las respuestas grandes; por eso
    # nunca devolvemos JSON largo ni una página de error, pase lo que pase.
    if TELEGRAM_WEBHOOK_SECRET and token != TELEGRAM_WEBHOOK_SECRET:
        return PlainTextResponse("token invalido", status_code=403)
    try:
        total = await run_in_threadpool(tareas.revisar_vencimientos)
        return PlainTextResponse(f"ok:{total}")
    except Exception as e:
        print(f"[tareas] error al revisar vencimientos: {e}")
        return PlainTextResponse("ok:error")
