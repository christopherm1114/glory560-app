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
# El secreto del webhook es opcional pero MUY recomendado.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# --- Tareas programadas (cron-job.org) ---
# Token propio para /tasks/revisar-vencimientos. Antes se reutilizaba el
# secreto del webhook, que viaja en la URL del cron y queda escrito en los
# registros de medio mundo: si se filtraba, se filtraba también el webhook.
# Si no se define, cae al secreto del webhook para no romper el despliegue
# actual, pero se avisa en el log para que se configure cuanto antes.
TASKS_TOKEN = os.environ.get("TASKS_TOKEN", "")
if not TASKS_TOKEN:
    TASKS_TOKEN = TELEGRAM_WEBHOOK_SECRET
    if TASKS_TOKEN:
        print("[config] AVISO: falta TASKS_TOKEN; se usa TELEGRAM_WEBHOOK_SECRET "
              "como respaldo. Define TASKS_TOKEN en Render.")

# --- Sesiones del panel web ---
# Con esto se firma la cookie de sesión. Antes se reutilizaba
# TELEGRAM_BOT_TOKEN: si ese token se filtraba, cualquiera podía fabricar una
# sesión válida de cualquier usuario, administrador incluido. Son dos secretos
# con vidas distintas y no deben compartirse.
# Si no se define, se cae al token del bot para no dejar la app sin arrancar,
# pero se avisa en el log. Al definirlo, las sesiones abiertas se cierran una
# vez y los usuarios vuelven a ingresar: es lo esperado.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = TELEGRAM_BOT_TOKEN
    print("[config] AVISO: falta SESSION_SECRET; se firma la sesión con "
          "TELEGRAM_BOT_TOKEN como respaldo. Define SESSION_SECRET en Render.")

# --- Supabase ---
SUPABASE_URL = _requerida("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _requerida("SUPABASE_SERVICE_KEY")

# --- Administrador (quien aprueba usuarios) ---
# Se guarda como número entero; si no se define, queda en 0.
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
