"""
auth.py
-------
Seguridad de la web: login por teléfono/contraseña y manejo de la sesión.

Por ahora, el usuario y la contraseña son el MISMO número de teléfono
(así lo pediste; la seguridad se reforzará más adelante). La sesión se
guarda en una cookie firmada, para no volver a pedir login en cada clic.

Todo con librerías estándar de Python (hashlib, hmac).
"""

import hashlib
import hmac
import time

import db
from config import TELEGRAM_BOT_TOKEN


def normalizar_telefono(valor: str) -> str:
    """Deja solo los dígitos, para que '+593 99...' y '09 9...' se comparen igual."""
    return "".join(c for c in str(valor or "") if c.isdigit())


# ---------- Login ----------

def validar_login(usuario: str, contrasena: str) -> dict | None:
    """
    Comprueba las credenciales. Devuelve el usuario si son correctas y su
    cuenta está aprobada; si no, devuelve None.
    """
    tel = normalizar_telefono(usuario)
    persona = db.buscar_usuario_por_telefono_normalizado(tel)
    if not persona:
        return None
    if persona.get("estado") != "aprobado":
        return None
    # La clave guardada (por defecto el teléfono) debe coincidir.
    if normalizar_telefono(persona.get("clave") or persona.get("telefono")) != normalizar_telefono(contrasena):
        return None
    return persona


# ---------- Cookie de sesión (firmada) ----------

def crear_cookie_sesion(usuario_id: int, horas: int = 168) -> str:
    """Crea un texto firmado 'usuario_id.expiracion.firma' (dura 7 días)."""
    expira = int(time.time()) + horas * 3600
    base = f"{usuario_id}.{expira}"
    firma = hmac.new(TELEGRAM_BOT_TOKEN.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"{base}.{firma}"


def leer_cookie_sesion(cookie: str | None) -> int | None:
    """Verifica la cookie y devuelve el usuario_id si es válida y no expiró."""
    if not cookie:
        return None
    try:
        usuario_id, expira, firma = cookie.split(".")
    except (ValueError, AttributeError):
        return None
    base = f"{usuario_id}.{expira}"
    calculado = hmac.new(TELEGRAM_BOT_TOKEN.encode(), base.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculado, firma):
        return None
    try:
        if int(expira) < time.time():
            return None
        return int(usuario_id)
    except ValueError:
        return None
