"""
conftest.py
-----------
Andamiaje de las pruebas. pytest lo carga solo, antes que cualquier test.

Existe por una razón concreta: importar `mantenimiento` arrastra `db`, y `db` abre
la conexión a Supabase en el momento de importarse. Sin esto, ejecutar las pruebas
exigiría credenciales reales y tocaría la base de datos de producción.

El cálculo en sí (`mantenimiento.calcular_estado`) no necesita nada de esto: es
aritmética sobre diccionarios. Este archivo solo evita el efecto colateral del
import. Si algún día `db` conectara de forma perezosa, se podría borrar.
"""

import os
import sys
import types

# Variables mínimas para que `config._requerida` no aborte. Valores de mentira:
# ninguna prueba habla con Telegram, Supabase ni Render.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "prueba")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "prueba")
os.environ.setdefault("SESSION_SECRET", "prueba")
os.environ.setdefault("TASKS_TOKEN", "prueba")
os.environ.setdefault("SUPABASE_URL", "https://pruebas.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "clave-de-prueba")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "0")


def _explota(*_args, **_kwargs):
    raise AssertionError(
        "Una prueba intentó usar la base de datos. Las pruebas del dominio deben "
        "pasar los datos como argumentos a mantenimiento.calcular_estado()."
    )


# Cliente de Supabase falso: cualquier uso real revienta con un mensaje claro en
# vez de fallar de forma confusa o, peor, conectarse de verdad.
_supabase = types.ModuleType("supabase")
_supabase.create_client = lambda *a, **k: types.SimpleNamespace(table=_explota)
_supabase.Client = object
sys.modules.setdefault("supabase", _supabase)
