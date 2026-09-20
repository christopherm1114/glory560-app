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
import threading
import time
from collections import defaultdict

import db
from config import SESSION_SECRET


# =====================================================================
# LIMITACIÓN DE INTENTOS
# =====================================================================
#
# Antes no existía ningún freno: se podían probar contraseñas y códigos de
# recuperación sin límite. Con contraseñas que son números de teléfono y
# códigos de seis dígitos, eso convierte la fuerza bruta en algo trivial.
#
# Se cuenta por dos claves a la vez —dirección IP y cuenta— porque cada una
# tapa el hueco de la otra: la IP frena a quien ataca muchas cuentas desde un
# mismo sitio, y la cuenta frena a quien ataca una sola cuenta desde muchas IP.

LIMITE_INTENTOS = 5        # fallos permitidos...
VENTANA_SEGUNDOS = 300     # ...dentro de esta ventana (5 minutos)
_MAX_CLAVES = 5000         # tope de memoria; ver _podar()

_fallos: dict[str, list[float]] = defaultdict(list)
_cerrojo = threading.Lock()


def _podar(ahora: float) -> None:
    """
    Descarta los registros vencidos. Sin esto, el propio contador sería un
    punto de agotamiento de memoria: bastaría con pedir login declarando una
    IP distinta cada vez para hacer crecer el diccionario sin fin.
    """
    vencidas = [k for k, v in _fallos.items()
                if not v or ahora - v[-1] > VENTANA_SEGUNDOS]
    for k in vencidas:
        del _fallos[k]


def intento_permitido(clave: str) -> bool:
    """Devuelve False si esa clave ya agotó sus intentos en la ventana."""
    if not clave:
        return True
    ahora = time.time()
    with _cerrojo:
        if len(_fallos) > _MAX_CLAVES:
            _podar(ahora)
        recientes = [t for t in _fallos.get(clave, []) if ahora - t < VENTANA_SEGUNDOS]
        _fallos[clave] = recientes
        return len(recientes) < LIMITE_INTENTOS


def registrar_fallo(clave: str) -> None:
    """Anota un intento fallido para esa clave."""
    if not clave:
        return
    with _cerrojo:
        _fallos[clave].append(time.time())


def limpiar_intentos(clave: str) -> None:
    """Borra el historial de la clave. Se llama tras un acierto."""
    if not clave:
        return
    with _cerrojo:
        _fallos.pop(clave, None)


def segundos_para_reintentar(clave: str) -> int:
    """Cuántos segundos faltan para que la clave vuelva a tener intentos."""
    with _cerrojo:
        intentos = list(_fallos.get(clave) or [])
    if len(intentos) < LIMITE_INTENTOS:
        return 0
    return max(0, int(VENTANA_SEGUNDOS - (time.time() - intentos[-LIMITE_INTENTOS])))


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

def debe_cambiar_clave(persona: dict) -> bool:
    """
    True si la cuenta todavía no tiene contraseña propia y sigue entrando con
    la credencial heredada (el teléfono). Su sesión solo sirve para cambiarla.
    """
    return not (persona or {}).get("clave_hash")


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


def marca_credencial(clave_hash: str | None) -> str:
    """
    Huella corta de la contraseña vigente. Va dentro de la cookie para que
    cambiar la contraseña invalide las sesiones abiertas.

    Antes la firma solo llevaba el usuario y la expiración, así que cambiar la
    contraseña no expulsaba a nadie: quien sospechaba de un intruso y la
    cambiaba seguía teniéndolo dentro, porque su cookie seguía siendo válida.
    """
    return hashlib.sha256((clave_hash or "sin-clave").encode()).hexdigest()[:12]


def crear_cookie_sesion(usuario_id: int, clave_hash: str | None = None,
                        minutos: int = MINUTOS_SESION) -> str:
    """Crea un texto firmado 'usuario_id.expiracion.marca.firma'."""
    expira = int(time.time()) + minutos * 60
    base = f"{usuario_id}.{expira}.{marca_credencial(clave_hash)}"
    firma = hmac.new(SESSION_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"{base}.{firma}"


def leer_cookie_sesion(cookie: str | None) -> tuple[int, str] | None:
    """
    Verifica la cookie y devuelve (usuario_id, marca) si es válida y no expiró.

    Quien llama debe comparar la marca con la de la contraseña actual del
    usuario; esa comparación necesita ir a la base de datos y aquí no se hace.
    Las cookies del formato anterior (sin marca) no validan: los usuarios
    vuelven a ingresar una vez tras el despliegue, que es lo esperado.
    """
    if not cookie:
        return None
    try:
        usuario_id, expira, marca, firma = cookie.split(".")
    except (ValueError, AttributeError):
        return None
    base = f"{usuario_id}.{expira}.{marca}"
    calculado = hmac.new(SESSION_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculado, firma):
        return None
    try:
        if int(expira) < time.time():
            return None
        return int(usuario_id), marca
    except ValueError:
        return None
