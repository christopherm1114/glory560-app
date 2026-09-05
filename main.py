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

import hmac

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from config import TELEGRAM_WEBHOOK_SECRET, TASKS_TOKEN
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
    if not hmac.compare_digest(x_telegram_bot_api_secret_token.encode(), TELEGRAM_WEBHOOK_SECRET.encode()):
        raise HTTPException(status_code=403, detail="Secreto inválido")

    update = await request.json()

    # Nuestro código de handlers es SÍNCRONO (usa la base de datos de forma
    # normal). Para no bloquear el servidor, lo corremos en un hilo aparte.
    await run_in_threadpool(handlers.procesar_update, update)

    # Telegram solo necesita un 200 OK; el contenido no importa.
    return {"ok": True}


# Acepta GET y POST para que cualquier programador externo (ej. cron-job.org)
# pueda llamarlo fácilmente. El token viaja en la cabecera X-Tasks-Token y no en
# la dirección: las URLs quedan escritas en los registros del servidor y en el
# historial del navegador, así que un token en la URL se filtra solo.
@app.get("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
@app.post("/tasks/revisar-vencimientos", response_class=PlainTextResponse)
async def revisar_vencimientos(x_tasks_token: str = Header(default="")):
    # SIEMPRE devolvemos una respuesta minúscula en texto plano.
    # cron-job.org (plan gratis) corta las respuestas grandes; por eso
    # nunca devolvemos JSON largo ni una página de error, pase lo que pase.
    if not hmac.compare_digest(x_tasks_token.encode(), TASKS_TOKEN.encode()):
        return PlainTextResponse("token invalido", status_code=403)
    try:
        total = await run_in_threadpool(tareas.revisar_vencimientos)
        return PlainTextResponse(f"ok:{total}")
    except Exception as e:
        print(f"[tareas] error al revisar vencimientos: {e}")
        return PlainTextResponse("ok:error")
