"""
db.py
-----
Acceso a la base de datos (Supabase / PostgreSQL).

Usamos el cliente oficial de Supabase. Cada función de aquí hace UNA cosa
concreta con la base de datos (buscar un usuario, crear un vehículo, etc.),
para que el resto del código quede limpio y fácil de leer.
"""

from datetime import datetime, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# Creamos el cliente una sola vez y lo reutilizamos en todo el programa.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ==================== USUARIOS ====================

def buscar_usuario_por_telegram(telegram_id: int) -> dict | None:
    """Devuelve el usuario con ese telegram_id, o None si no existe."""
    resp = supabase.table("usuarios").select("*").eq("telegram_id", telegram_id).execute()
    return resp.data[0] if resp.data else None


def buscar_usuario_por_telefono(telefono: str) -> dict | None:
    resp = supabase.table("usuarios").select("*").eq("telefono", telefono).execute()
    return resp.data[0] if resp.data else None


def crear_usuario(telegram_id: int, telefono: str, nombre: str) -> dict:
    """Crea un usuario nuevo en estado 'pendiente' y lo devuelve."""
    resp = supabase.table("usuarios").insert({
        "telegram_id": telegram_id,
        "telefono": telefono,
        "nombre": nombre,
        "estado": "pendiente",
        "rol": "usuario",
    }).execute()
    return resp.data[0]


def actualizar_usuario(usuario_id: int, cambios: dict) -> None:
    supabase.table("usuarios").update(cambios).eq("id", usuario_id).execute()


def listar_usuarios_pendientes() -> list[dict]:
    resp = supabase.table("usuarios").select("*").eq("estado", "pendiente").execute()
    return resp.data or []


# ==================== VARIANTES ====================

def buscar_variante(motor: str, transmision: str) -> dict | None:
    """Busca la variante exacta a partir del motor y la transmisión."""
    resp = (supabase.table("variantes").select("*")
            .eq("motor", motor).eq("transmision", transmision).execute())
    return resp.data[0] if resp.data else None


def obtener_variante(variante_id: int) -> dict | None:
    resp = supabase.table("variantes").select("*").eq("id", variante_id).execute()
    return resp.data[0] if resp.data else None


# ==================== VEHÍCULOS ====================

def crear_vehiculo(usuario_id: int, variante_id: int, placa: str, anio: int | None,
                   kilometraje: int, fecha_ultimo_aceite: str | None) -> dict:
    resp = supabase.table("vehiculos").insert({
        "usuario_id": usuario_id,
        "variante_id": variante_id,
        "placa": placa,
        "anio_modelo": anio,
        "kilometraje_actual": kilometraje,
        "fecha_actualizacion_km": _hoy(),
        "fecha_ultimo_aceite": fecha_ultimo_aceite,
    }).execute()
    return resp.data[0]


def buscar_vehiculo_de_usuario(usuario_id: int) -> dict | None:
    """Devuelve el (primer) vehículo del usuario, o None."""
    resp = supabase.table("vehiculos").select("*").eq("usuario_id", usuario_id).execute()
    return resp.data[0] if resp.data else None


def actualizar_vehiculo(vehiculo_id: int, cambios: dict) -> None:
    supabase.table("vehiculos").update(cambios).eq("id", vehiculo_id).execute()


def listar_todos_los_vehiculos() -> list[dict]:
    """Usado por la tarea de recordatorios."""
    resp = supabase.table("vehiculos").select("*").execute()
    return resp.data or []


# ==================== MANTENIMIENTOS ====================

def listar_tipos_mantenimiento() -> list[dict]:
    resp = supabase.table("tipos_mantenimiento").select("*").order("id").execute()
    return resp.data or []


def obtener_tipo(tipo_id: int) -> dict | None:
    resp = supabase.table("tipos_mantenimiento").select("*").eq("id", tipo_id).execute()
    return resp.data[0] if resp.data else None


def intervalos_de_variante(variante_id: int) -> list[dict]:
    """Devuelve los intervalos configurados para una variante."""
    resp = supabase.table("intervalos").select("*").eq("variante_id", variante_id).execute()
    return resp.data or []


def crear_mantenimiento(vehiculo_id: int, tipo_id: int, fecha: str, kilometraje: int,
                        costo: float | None, taller: str | None, notas: str | None) -> dict:
    resp = supabase.table("mantenimientos").insert({
        "vehiculo_id": vehiculo_id,
        "tipo_mantenimiento_id": tipo_id,
        "fecha": fecha,
        "kilometraje": kilometraje,
        "costo": costo,
        "taller": taller,
        "notas": notas,
    }).execute()
    return resp.data[0]


def ultimo_mantenimiento(vehiculo_id: int, tipo_id: int) -> dict | None:
    """El mantenimiento más reciente (por km) de ese tipo para ese vehículo."""
    resp = (supabase.table("mantenimientos").select("*")
            .eq("vehiculo_id", vehiculo_id)
            .eq("tipo_mantenimiento_id", tipo_id)
            .order("kilometraje", desc=True).limit(1).execute())
    return resp.data[0] if resp.data else None


def historial(vehiculo_id: int, limite: int = 15) -> list[dict]:
    resp = (supabase.table("mantenimientos").select("*")
            .eq("vehiculo_id", vehiculo_id)
            .order("fecha", desc=True).limit(limite).execute())
    return resp.data or []


# ==================== ALERTAS ====================

def crear_alerta(vehiculo_id: int, tipo_id: int, fecha_programada: str) -> dict:
    resp = supabase.table("alertas").insert({
        "vehiculo_id": vehiculo_id,
        "tipo_mantenimiento_id": tipo_id,
        "fecha_programada": fecha_programada,
        "fecha_enviada": _ahora_iso(),
        "estado": "enviada",
    }).execute()
    return resp.data[0]


def alerta_reciente_existe(vehiculo_id: int, tipo_id: int, dias: int = 7) -> bool:
    """
    Evita spam: solo considera 'reciente' una alerta enviada en los últimos
    'dias' (por defecto 7). Así, si un mantenimiento sigue pendiente, se vuelve
    a recordar a la semana siguiente, pero no todos los días.
    """
    from datetime import datetime, timezone, timedelta
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    resp = (supabase.table("alertas").select("id")
            .eq("vehiculo_id", vehiculo_id)
            .eq("tipo_mantenimiento_id", tipo_id)
            .gte("fecha_enviada", limite).limit(1).execute())
    return bool(resp.data)


# ==================== ESTADO DE CONVERSACIÓN ====================

def obtener_estado(telegram_id: int) -> dict:
    """Devuelve {paso, datos}. Si no hay nada, devuelve paso=None y datos={}."""
    resp = supabase.table("estado_conversacion").select("*").eq("telegram_id", telegram_id).execute()
    if resp.data:
        fila = resp.data[0]
        return {"paso": fila.get("paso"), "datos": fila.get("datos") or {}}
    return {"paso": None, "datos": {}}


def guardar_estado(telegram_id: int, paso: str, datos: dict) -> None:
    """Guarda (o actualiza) el paso actual y los datos parciales del usuario."""
    supabase.table("estado_conversacion").upsert({
        "telegram_id": telegram_id,
        "paso": paso,
        "datos": datos,
        "actualizado": _ahora_iso(),
    }).execute()


def limpiar_estado(telegram_id: int) -> None:
    """Borra la conversación en curso (cuando termina o se cancela)."""
    supabase.table("estado_conversacion").delete().eq("telegram_id", telegram_id).execute()


# ==================== Ayudas de fecha ====================

def _hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
