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
import secrets
import time

import db
from config import TELEGRAM_BOT_TOKEN


def normalizar_telefono(valor: str) -> str:
    """Deja solo los dígitos, para que '+593 99...' y '09 9...' se comparen igual."""
    return "".join(c for c in str(valor or "") if c.isdigit())


# ---------- Cifrado de contraseñas (hash PBKDF2) ----------

def hash_password(contrasena: str) -> str:
    """
    Cifra la contraseña con PBKDF2-SHA256 y una 'sal' aleatoria.
    Devuelve un texto 'pbkdf2_sha256$iteraciones$sal$hash' que se guarda en la BD.
    Nunca se guarda la contraseña en texto plano.
    """
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", contrasena.encode(), bytes.fromhex(sal), 120000)
    return f"pbkdf2_sha256$120000${sal}${dk.hex()}"


def verificar_password(contrasena: str, guardado: str) -> bool:
    """Comprueba una contraseña contra su hash guardado."""
    try:
        _algo, iteraciones, sal, h = guardado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", contrasena.encode(), bytes.fromhex(sal), int(iteraciones))
        return hmac.compare_digest(dk.hex(), h)
    except (ValueError, AttributeError):
        return False


def contrasena_valida(contrasena: str) -> bool:
    """Requisito: mínimo 8 caracteres, con al menos una letra y un número."""
    c = str(contrasena or "")
    return len(c) >= 8 and any(x.isalpha() for x in c) and any(x.isdigit() for x in c)


def generar_codigo() -> str:
    """Genera un código de recuperación de 6 dígitos, aleatorio y seguro."""
    return f"{secrets.randbelow(1000000):06d}"


def verificar_credencial(persona: dict, contrasena: str) -> bool:
    """
    Verifica una contraseña contra la persona:
      - Si ya tiene contraseña cifrada (clave_hash), la compara con el hash.
      - Si aún no (usuario nuevo/heredado), la clave sigue siendo el teléfono.
    """
    ch = persona.get("clave_hash")
    if ch:
        return verificar_password(contrasena, ch)
    # Heredado: la clave es el teléfono. Tolerante al código de país (últimos 9 dígitos).
    a = normalizar_telefono(persona.get("clave") or persona.get("telefono"))
    b = normalizar_telefono(contrasena)
    return a == b or (len(a) >= 9 and len(b) >= 9 and a[-9:] == b[-9:])


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
    if not verificar_credencial(persona, contrasena):
        return None
    return persona


# ---------- Cookie de sesión (firmada) ----------

# Minutos que dura la sesión SIN actividad. Se renueva en cada uso, así que
# un usuario activo no se desconecta; si deja de usar la app, expira sola.
MINUTOS_SESION = 12


def crear_cookie_sesion(usuario_id: int, minutos: int = MINUTOS_SESION) -> str:
    """Crea un texto firmado 'usuario_id.expiracion.firma' (sesión corta y deslizante)."""
    expira = int(time.time()) + minutos * 60
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
