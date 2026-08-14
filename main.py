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

from config import TELEGRAM_WEBHOOK_SECRET
import handlers, tareas

app = FastAPI(title="Control de Mantenimientos Glory 560")


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


@app.post("/tasks/revisar-vencimientos")
async def revisar_vencimientos():
    """Permite disparar los recordatorios manualmente (útil para probar)."""
    total = await run_in_threadpool(tareas.revisar_vencimientos)
    return {"alertas_enviadas": total}
