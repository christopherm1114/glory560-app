"""
telegram.py
-----------
Funciones para HABLAR con Telegram (enviar mensajes, botones, etc.).

Telegram tiene una "API HTTP": para enviar un mensaje, hacemos una petición
HTTP a una URL especial. Aquí encapsulamos eso para no repetir código.

Documentación oficial: https://core.telegram.org/bots/api
"""

import httpx
from config import TELEGRAM_BOT_TOKEN

# Todas las llamadas van a esta URL base, que incluye el token del bot.
_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _llamar(metodo: str, datos: dict) -> dict:
    """Hace una petición POST a la API de Telegram y devuelve la respuesta."""
    respuesta = httpx.post(f"{_API}/{metodo}", json=datos, timeout=20)
    respuesta.raise_for_status()  # si Telegram devuelve error, lo lanza como excepción
    return respuesta.json()


def enviar_mensaje(chat_id: int, texto: str, teclado: dict | None = None) -> dict:
    """
    Envía un mensaje de texto a un chat.
    'teclado' es opcional: sirve para mostrar botones (ver funciones de abajo).
    """
    datos = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",  # permite usar <b>negrita</b> en el texto
    }
    if teclado:
        datos["reply_markup"] = teclado
    return _llamar("sendMessage", datos)


def responder_callback(callback_id: str, texto: str = "") -> dict:
    """
    Cuando el usuario toca un botón "inline", Telegram espera una confirmación.
    Esto quita el "relojito" de carga del botón.
    """
    return _llamar("answerCallbackQuery", {"callback_query_id": callback_id, "text": texto})


# ---------- Ayudas para construir teclados (botones) ----------

def boton_compartir_telefono(texto_boton: str = "📱 Compartir mi número") -> dict:
    """
    Teclado especial que pide al usuario compartir su número de teléfono.
    Telegram lo entrega ya verificado (no hay que enviar SMS).
    'one_time_keyboard' hace que el teclado desaparezca tras usarlo.
    """
    return {
        "keyboard": [[{"text": texto_boton, "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def quitar_teclado() -> dict:
    """Oculta cualquier teclado personalizado que estuviera visible."""
    return {"remove_keyboard": True}


def teclado_inline(botones: list[list[tuple[str, str]]]) -> dict:
    """
    Construye un teclado de botones "inline" (aparecen bajo el mensaje).
    'botones' es una lista de filas; cada fila es una lista de (texto, dato).
    'dato' es lo que recibimos cuando el usuario toca el botón (callback_data).

    Ejemplo:
        teclado_inline([[("1.8 Aspirado", "motor:1.8"), ("1.5 Turbo", "motor:1.5T")]])
    """
    filas = []
    for fila in botones:
        filas.append([{"text": texto, "callback_data": dato} for (texto, dato) in fila])
    return {"inline_keyboard": filas}


# ---------- Configuración del webhook ----------

def configurar_webhook(url: str, secreto: str = "") -> dict:
    """
    Le dice a Telegram: 'cuando llegue un mensaje a mi bot, avísame en esta URL'.
    Se ejecuta UNA sola vez (o cuando cambie la URL). Ver README.
    """
    datos = {"url": url}
    if secreto:
        # Telegram enviará este secreto en un encabezado; así verificamos que
        # la petición viene de Telegram y no de un tercero.
        datos["secret_token"] = secreto
    return _llamar("setWebhook", datos)
