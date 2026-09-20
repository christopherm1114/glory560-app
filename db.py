"""
db.py
-----
Acceso a la base de datos (Supabase / PostgreSQL).

Usamos el cliente oficial de Supabase. Cada función de aquí hace UNA cosa
concreta con la base de datos (buscar un usuario, crear un vehículo, etc.),
para que el resto del código quede limpio y fácil de leer.
"""

import threading
import time
from datetime import datetime, timezone
from supabase import create_client, Client
from supabase.client import ClientOptions
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# Creamos el cliente una sola vez y lo reutilizamos en todo el programa.
#
# El timeout es importante: sin él, una consulta que no responde deja colgado
# un hilo del grupo que usa FastAPI (son 40). Con el bot y el panel pidiendo a
# la vez, unas pocas consultas colgadas congelaban la aplicacion entera.
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    options=ClientOptions(postgrest_client_timeout=15, storage_client_timeout=15),
)


# ==================== CACHÉ DE CATÁLOGOS ====================
#
# 'tipos_mantenimiento' e 'intervalos' son catálogos de solo lectura: ninguna
# ruta de la app los modifica (solo se tocan a mano desde Supabase). Traerlos
# en cada mensaje del bot costaba dos viajes de red por comando. Se guardan en
# memoria con vencimiento corto: si los editas en Supabase, el cambio entra
# solo, a más tardar en _VIDA_CACHE segundos.

_VIDA_CACHE = 600  # segundos (10 minutos)
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_candado = threading.Lock()


def _cacheado(clave: str, consulta) -> list[dict]:
    """Devuelve el resultado de 'consulta', reusándolo mientras no venza."""
    ahora = time.monotonic()
    with _cache_candado:
        guardado = _cache.get(clave)
        if guardado and (ahora - guardado[0]) < _VIDA_CACHE:
            return guardado[1]
    datos = consulta() or []
    with _cache_candado:
        _cache[clave] = (ahora, datos)
    return datos


def limpiar_cache() -> None:
    """Vacía la caché de catálogos (útil tras editar los datos en Supabase)."""
    with _cache_candado:
        _cache.clear()


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
    Busca por teléfono comparando solo los dígitos. Es tolerante al código de
    país: '0999123456', '+593 999123456' y '593999123456' se consideran el mismo
    número (comparando los últimos 9 dígitos). Así el prefijo +593 no rompe nada.
    """
    if not telefono_digitos:
        return None
    obj9 = telefono_digitos[-9:]
    for u in supabase.table("usuarios").select("*").execute().data or []:
        guardado = "".join(c for c in str(u.get("telefono") or "") if c.isdigit())
        if not guardado:
            continue
        if guardado == telefono_digitos or (len(guardado) >= 9 and guardado[-9:] == obj9):
            return u
    return None


def buscar_usuarios(texto: str) -> list[dict]:
    """
    Busca usuarios por nombre o teléfono (para la viñeta de Roles).

    El texto se reduce a letras, números y espacios antes de construir el
    patrón. El cliente de Supabase arma una consulta REST, no SQL, pero el
    filtro se escribe como texto y caracteres como la coma, el punto o los
    paréntesis alteran su estructura. Antes solo se neutralizaba la coma.
    """
    limpio = "".join(c for c in str(texto or "") if c.isalnum() or c.isspace())
    patron = "%" + limpio.strip()[:60] + "%"
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
    vehiculo = resp.data[0]

    # Dejamos sentado el kilometraje con el que entra el vehículo. Es la línea
    # base de los cálculos: sin ella, un auto que se registra con 45.000 km
    # aparecía con todos los controles vencidos desde el primer día, porque
    # el motor asumía que el último servicio fue a los 0 km.
    try:
        registrar_lectura_km(vehiculo["id"], kilometraje)
    except Exception as e:
        print(f"[db] no se pudo registrar la lectura inicial de km: {e}")
    return vehiculo


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
    """Catálogo de controles. Cacheado: es de solo lectura (ver _cacheado)."""
    return _cacheado(
        "tipos",
        lambda: supabase.table("tipos_mantenimiento").select("*").order("id").execute().data,
    )


def obtener_tipo(tipo_id: int) -> dict | None:
    resp = supabase.table("tipos_mantenimiento").select("*").eq("id", tipo_id).execute()
    return resp.data[0] if resp.data else None


def intervalos_de_variante(variante_id: int) -> list[dict]:
    """Devuelve los intervalos configurados para una variante (cacheado)."""
    return _cacheado(
        f"intervalos:{variante_id}",
        lambda: supabase.table("intervalos").select("*")
        .eq("variante_id", variante_id).execute().data,
    )


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


def km_base_vehiculo(vehiculo_id: int) -> int | None:
    """
    Kilometraje con el que el vehículo entró al sistema: la PRIMERA lectura
    en orden cronológico. Sirve de punto de partida para los controles que
    todavía no tienen ningún servicio en el historial.

    Se ordena por fecha (y por id, para desempatar dos lecturas del mismo día),
    NO por kilometraje. Parece equivalente y no lo es: nada impide teclear mal
    el odómetro, y en la base real hay vehículos con una lectura suelta muy por
    debajo del resto. Tomando el mínimo, esa cifra errónea se convertía en la
    línea base y el auto aparecía con todo vencido; tomando la primera por
    fecha, un error posterior no arrastra el cálculo hacia atrás.

    Devuelve None si el vehículo no tiene ninguna lectura guardada; quien
    llama decide qué usar en ese caso.
    """
    resp = (supabase.table("lecturas_km").select("kilometraje")
            .eq("vehiculo_id", vehiculo_id)
            .order("fecha").order("id").limit(1).execute())
    if not resp.data:
        return None
    try:
        return int(resp.data[0]["kilometraje"])
    except (TypeError, ValueError, KeyError):
        return None


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

# Una conversación abandonada caduca a las 6 horas. Sin esto, quien dejaba un
# registro a medias quedaba atrapado: días después, cualquier texto suelto que
# escribiera se interpretaba como la respuesta a aquella pregunta olvidada, y
# la única salida era adivinar /cancelar. En la base de producción había dos
# usuarios atascados desde hacía semanas.
HORAS_VIDA_CONVERSACION = 6


def _conversacion_caducada(actualizado) -> bool:
    """True si la conversación quedó abandonada hace más de las horas límite."""
    if not actualizado:
        return False
    try:
        momento = datetime.fromisoformat(str(actualizado).replace("Z", "+00:00"))
    except ValueError:
        return False
    if momento.tzinfo is None:  # las filas viejas se guardaron sin zona horaria
        momento = momento.replace(tzinfo=timezone.utc)
    horas = (datetime.now(timezone.utc) - momento).total_seconds() / 3600
    return horas > HORAS_VIDA_CONVERSACION


def obtener_estado(telegram_id: int) -> dict:
    """Devuelve {paso, datos}. Si no hay nada, devuelve paso=None y datos={}."""
    resp = supabase.table("estado_conversacion").select("*").eq("telegram_id", telegram_id).execute()
    if resp.data:
        fila = resp.data[0]
        if _conversacion_caducada(fila.get("actualizado")):
            limpiar_estado(telegram_id)
            return {"paso": None, "datos": {}}
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
