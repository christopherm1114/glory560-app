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

# Un solo cliente para todo el programa, en vez de abrir una conexión nueva
# por mensaje. Cada conexión nueva paga el saludo TLS con Telegram (~300 ms);
# reutilizándola, el segundo mensaje y los siguientes salen casi gratis.
# httpx.Client es seguro entre hilos, que es como lo usa FastAPI aquí.
_TIEMPOS = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_cliente = httpx.Client(timeout=_TIEMPOS,
                        limits=httpx.Limits(max_keepalive_connections=5,
                                            max_connections=10))


def _llamar(metodo: str, datos: dict) -> dict:
    """
    Hace una petición POST a la API de Telegram y devuelve la respuesta.

    Reintenta UNA vez ante un fallo de red. Las conexiones que el cliente
    mantiene abiertas pueden haber caducado del otro lado mientras el
    servicio dormía; el primer intento falla y el segundo, ya con conexión
    nueva, funciona. Sin esto, el primer mensaje tras despertar se perdía.
    """
    ultimo_error: Exception | None = None
    for intento in (1, 2):
        try:
            respuesta = _cliente.post(f"{_API}/{metodo}", json=datos)
            respuesta.raise_for_status()  # si Telegram devuelve error, lo lanza
            return respuesta.json()
        except httpx.TransportError as e:
            # Solo los errores de transporte (red, timeout) merecen reintento;
            # un 400 de Telegram va a fallar igual la segunda vez.
            ultimo_error = e
            print(f"[telegram] fallo de red en {metodo} (intento {intento}): {e}")
    raise ultimo_error  # type: ignore[misc]


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


def enviar_documento(chat_id: int, nombre: str, contenido: bytes,
                     descripcion: str = "") -> dict:
    """
    Envía un archivo a un chat. Se usa para dejar el respaldo de la base de
    datos en la conversación del administrador: queda fuera del servidor, en
    un sitio al que él siempre tiene acceso, sin montar nada más.
    """
    respuesta = _cliente.post(
        f"{_API}/sendDocument",
        data={"chat_id": chat_id, "caption": descripcion[:1000], "parse_mode": "HTML"},
        files={"document": (nombre, contenido, "application/json")},
    )
    respuesta.raise_for_status()
    return respuesta.json()


# ---------- Avisos al administrador ----------

# Sin esto, un error solo quedaba impreso en los registros de Render, que
# rotan y nadie mira: el bot podía estar fallando durante días sin que nadie
# lo supiera. Se avisa por Telegram, que es donde el administrador ya está.
_ULTIMOS_AVISOS: dict[str, float] = {}
MINUTOS_ENTRE_AVISOS_IGUALES = 30


def avisar_al_admin(asunto: str, detalle: str = "") -> None:
    """
    Manda un aviso al administrador. Nunca lanza excepción: si el aviso falla,
    el problema original ya es bastante y no conviene taparlo con otro.

    Repite como mucho un aviso igual cada media hora, para que un error que se
    dispara en bucle no convierta el chat en un cañón de mensajes.
    """
    import time
    from config import ADMIN_TELEGRAM_ID

    if not ADMIN_TELEGRAM_ID:
        return
    ahora = time.time()
    anterior = _ULTIMOS_AVISOS.get(asunto, 0)
    if ahora - anterior < MINUTOS_ENTRE_AVISOS_IGUALES * 60:
        return
    _ULTIMOS_AVISOS[asunto] = ahora

    texto = f"⚠️ <b>{asunto}</b>"
    if detalle:
        # Telegram corta a los 4096 caracteres; se deja margen.
        recorte = detalle[-1200:]
        texto += f"\n\n<pre>{recorte}</pre>"
    try:
        enviar_mensaje(ADMIN_TELEGRAM_ID, texto)
    except Exception as e:
        print(f"[telegram] no se pudo avisar al administrador: {e}")


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
