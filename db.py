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
        "clave": telefono,   # contraseña inicial para la web = el teléfono
    }).execute()
    return resp.data[0]


def actualizar_usuario(usuario_id: int, cambios: dict) -> None:
    supabase.table("usuarios").update(cambios).eq("id", usuario_id).execute()


def actualizar_clave_hash(usuario_id: int, clave_hash: str) -> None:
    """Guarda la nueva contraseña ya cifrada (hash)."""
    supabase.table("usuarios").update({"clave_hash": clave_hash}).eq("id", usuario_id).execute()


def guardar_reset(usuario_id: int, codigo: str, expira_iso: str) -> None:
    """Guarda el código temporal de recuperación y su vencimiento."""
    supabase.table("usuarios").update(
        {"reset_codigo": codigo, "reset_expira": expira_iso}
    ).eq("id", usuario_id).execute()


def limpiar_reset(usuario_id: int) -> None:
    """Borra el código de recuperación (tras usarlo)."""
    supabase.table("usuarios").update(
        {"reset_codigo": None, "reset_expira": None}
    ).eq("id", usuario_id).execute()


def listar_usuarios_pendientes() -> list[dict]:
    resp = supabase.table("usuarios").select("*").eq("estado", "pendiente").execute()
    return resp.data or []


def obtener_usuario(usuario_id: int) -> dict | None:
    resp = supabase.table("usuarios").select("*").eq("id", usuario_id).execute()
    return resp.data[0] if resp.data else None


def listar_usuarios_aprobados() -> list[dict]:
    resp = (supabase.table("usuarios").select("*")
            .eq("estado", "aprobado").order("nombre").execute())
    return resp.data or []


def buscar_usuario_por_telefono_normalizado(telefono_digitos: str) -> dict | None:
    """
    Busca por teléfono comparando solo los dígitos (ignora '+', espacios, etc.).
    Como la base es pequeña, traemos los usuarios y comparamos en Python.
    """
    resp = supabase.table("usuarios").select("*").execute()
    for u in resp.data or []:
        guardado = "".join(c for c in str(u.get("telefono") or "") if c.isdigit())
        if guardado == telefono_digitos and telefono_digitos:
            return u
    return None


def buscar_usuarios(texto: str) -> list[dict]:
    """Busca usuarios por nombre o teléfono (para la viñeta de Roles)."""
    patron = "%" + texto.replace(",", " ").strip() + "%"
    resp = (supabase.table("usuarios").select("*")
            .or_(f"nombre.ilike.{patron},telefono.ilike.{patron}")
            .limit(20).execute())
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


def obtener_mantenimiento(mant_id: int) -> dict | None:
    resp = supabase.table("mantenimientos").select("*").eq("id", mant_id).execute()
    return resp.data[0] if resp.data else None


def eliminar_mantenimiento(mant_id: int) -> None:
    supabase.table("mantenimientos").delete().eq("id", mant_id).execute()


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
            .order("fecha", desc=True).order("id", desc=True).limit(limite).execute())
    return resp.data or []


def promedios_por_tipo(costo_max: float = 5000.0) -> dict:
    """
    Precio promedio de CADA tipo de mantenimiento, con los costos que registran
    TODOS los usuarios. Ignora costos no positivos o exageradamente altos
    (errores de tipeo). Devuelve {tipo_id: {"promedio": x, "conteo": n}}.
    """
    resp = supabase.table("mantenimientos").select("tipo_mantenimiento_id, costo").execute()
    acumulado: dict[int, list[float]] = {}
    for r in resp.data or []:
        c = r.get("costo")
        if c is None:
            continue
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if c <= 0 or c > costo_max:
            continue
        acumulado.setdefault(r["tipo_mantenimiento_id"], []).append(c)
    return {t: {"promedio": round(sum(v) / len(v), 2), "conteo": len(v)}
            for t, v in acumulado.items()}


def gastos_por_categoria(vehiculo_id: int) -> list[dict]:
    """Suma los costos de los mantenimientos agrupados por categoría del control."""
    tipos = {t["id"]: t for t in listar_tipos_mantenimiento()}
    resp = (supabase.table("mantenimientos").select("tipo_mantenimiento_id, costo")
            .eq("vehiculo_id", vehiculo_id).execute())
    acumulado: dict[str, float] = {}
    for r in resp.data or []:
        if r.get("costo") in (None, 0):
            continue
        categoria = tipos.get(r["tipo_mantenimiento_id"], {}).get("categoria") or "Otro"
        acumulado[categoria] = acumulado.get(categoria, 0.0) + float(r["costo"])
    return [{"categoria": k, "total": round(v, 2)} for k, v in sorted(acumulado.items())]


# ==================== LECTURAS DE KILOMETRAJE ====================

def registrar_lectura_km(vehiculo_id: int, kilometraje: int, fecha: str | None = None) -> None:
    """Guarda una lectura de kilometraje (para el gráfico de historial)."""
    supabase.table("lecturas_km").insert({
        "vehiculo_id": vehiculo_id,
        "kilometraje": kilometraje,
        "fecha": fecha or _hoy(),
    }).execute()


def historial_km(vehiculo_id: int, limite: int = 100) -> list[dict]:
    resp = (supabase.table("lecturas_km").select("fecha, kilometraje")
            .eq("vehiculo_id", vehiculo_id)
            .order("fecha").limit(limite).execute())
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

# Ecuador está en UTC-5 (todo el año, sin horario de verano).
from datetime import timedelta as _timedelta
_TZ_ECUADOR = timezone(_timedelta(hours=-5))


def _hoy() -> str:
    """Fecha de HOY en horario de Ecuador (para que 'hoy' sea el día local)."""
    return datetime.now(_TZ_ECUADOR).date().isoformat()


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
