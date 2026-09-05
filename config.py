"""
config.py
---------
Lee las variables de entorno (los "secretos" y ajustes de la app).

En tu computadora, estas variables se cargan desde el archivo .env.
En Render, se configuran en el panel del servicio (Environment).
"""

import os
from dotenv import load_dotenv

# Carga el archivo .env si existe (en Render no existe, y no pasa nada:
# ahí las variables ya vienen del sistema).
load_dotenv()


def _requerida(nombre: str) -> str:
    """Obtiene una variable obligatoria; si falta, avisa con un error claro."""
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(
            f"Falta la variable de entorno '{nombre}'. "
            f"Revisa tu archivo .env (local) o la configuración de Render."
        )
    return valor


# --- Telegram ---
TELEGRAM_BOT_TOKEN = _requerida("TELEGRAM_BOT_TOKEN")
# Obligatoria: cuando estaba vacía, la comprobación del webhook se saltaba
# entera y cualquiera podía enviar mensajes falsos haciéndose pasar por el admin.
TELEGRAM_WEBHOOK_SECRET = _requerida("TELEGRAM_WEBHOOK_SECRET")

# --- Secretos propios de la aplicación ---
# Un secreto por cada frontera de confianza. Antes la cookie se firmaba con
# TELEGRAM_BOT_TOKEN, que además viaja en cada URL de la API de Telegram: si se
# filtraba, se podían fabricar sesiones de cualquier usuario, admin incluido.
SESSION_SECRET = _requerida("SESSION_SECRET")
TASKS_TOKEN = _requerida("TASKS_TOKEN")

# --- Supabase ---
SUPABASE_URL = _requerida("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _requerida("SUPABASE_SERVICE_KEY")

# --- Administrador (quien aprueba usuarios) ---
# Se guarda como número entero; si no se define, queda en 0.
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
