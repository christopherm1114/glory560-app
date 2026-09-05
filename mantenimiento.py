"""
mantenimiento.py
----------------
La "inteligencia" de la app: calcula qué mantenimientos están por vencer.

Idea general para cada control (aceite, filtros, etc.):
  1. Buscamos cada cuánto toca (intervalo_km / intervalo_meses) según la variante.
  2. Vemos cuándo se hizo por última vez (del historial); si nunca, partimos
     del kilometraje/fecha de referencia del vehículo.
  3. Calculamos el próximo objetivo y cuánto falta.
  4. Clasificamos: 'vencido', 'proximo' o 'al_dia'.
"""

from datetime import date, datetime
import db

# Umbrales para considerar un mantenimiento "próximo a vencer".
KM_AVISO = 500       # avisar cuando falten 500 km o menos
DIAS_AVISO = 15      # o cuando falten 15 días o menos


def _a_fecha(texto: str | None) -> date | None:
    """Convierte 'YYYY-MM-DD' en un objeto date. Devuelve None si no hay dato."""
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto)).date()
    except ValueError:
        try:
            return datetime.strptime(str(texto), "%Y-%m-%d").date()
        except ValueError:
            return None


def km_base_vehiculo(vehiculo: dict) -> int:
    """
    Kilometraje desde el que se mide un control que NUNCA se ha registrado.

    Es el kilometraje con el que el vehículo entró al sistema, no el actual: si
    fuera el actual, el objetivo se alejaría a la par que el odómetro y el
    control no vencería jamás. Los vehículos creados antes de la migración 002
    no tienen la columna, y para ellos se usa el kilometraje actual como
    aproximación — es transitorio, la migración rellena el valor real.
    """
    inicial = vehiculo.get("kilometraje_inicial")
    if inicial is None:
        return vehiculo.get("kilometraje_actual") or 0
    return inicial


def calcular_estado(
    vehiculo: dict,
    tipos_mantenimiento: list[dict],
    historial: list[dict],
    intervalos: list[dict],
    hoy: date | None = None,
) -> list[dict]:
    """
    Cálculo puro: recibe los datos ya leídos y no consulta la base de datos.

    Está separado de `calcular_estado_vehiculo` para poder probarlo con datos
    inventados. `hoy` se recibe como argumento por el mismo motivo: si leyera
    date.today() por dentro, el resultado de una prueba cambiaría con el día.
    """
    km_actual = vehiculo.get("kilometraje_actual") or 0
    km_inicial = km_base_vehiculo(vehiculo)
    hoy = hoy or date.today()

    # Diccionario id_tipo -> tipo (para nombre, categoría, clase).
    tipos = {t["id"]: t for t in tipos_mantenimiento}

    # Del historial completo guardamos el ÚLTIMO servicio de cada tipo, por km.
    ultimos: dict = {}
    for m in historial:
        tid = m["tipo_mantenimiento_id"]
        prev = ultimos.get(tid)
        if prev is None or (m.get("kilometraje") or 0) > (prev.get("kilometraje") or 0):
            ultimos[tid] = m

    resultados = []
    for intervalo in intervalos:
        tipo_id = intervalo["tipo_mantenimiento_id"]
        tipo = tipos.get(tipo_id, {})
        nombre = tipo.get("nombre", f"Control {tipo_id}")
        categoria = tipo.get("categoria", "") or "Otros"
        clase = tipo.get("clase", "reemplazo")

        intervalo_km = intervalo.get("intervalo_km")
        intervalo_meses = intervalo.get("intervalo_meses")

        # ¿Cuándo se hizo por última vez? (del diccionario, sin consultar la BD)
        ultimo = ultimos.get(tipo_id)
        if ultimo:
            km_base = ultimo.get("kilometraje") or 0
            fecha_base = _a_fecha(ultimo.get("fecha"))
        else:
            # Nunca registrado: partimos del estado con el que entró el vehículo.
            # Antes esto era 0, y un vehículo dado de alta con 45.000 km veía
            # todos sus controles en rojo desde el primer día.
            km_base = km_inicial
            fecha_base = _a_fecha(vehiculo.get("fecha_ultimo_aceite")) \
                or _a_fecha(vehiculo.get("fecha_actualizacion_km"))

        # --- Cálculo por kilometraje ---
        km_restante = None
        if intervalo_km:
            proximo_km = km_base + intervalo_km
            km_restante = proximo_km - km_actual

        # --- Cálculo por tiempo ---
        dias_restantes = None
        if intervalo_meses and fecha_base:
            # Aproximamos meses como bloques de 30 días (suficiente para avisar).
            proximo_dia = fecha_base.toordinal() + intervalo_meses * 30
            dias_restantes = proximo_dia - hoy.toordinal()

        # --- Clasificación (lo que venza primero manda) ---
        estado = "al_dia"
        if (km_restante is not None and km_restante <= 0) or \
           (dias_restantes is not None and dias_restantes <= 0):
            estado = "vencido"
        elif (km_restante is not None and km_restante <= KM_AVISO) or \
             (dias_restantes is not None and dias_restantes <= DIAS_AVISO):
            estado = "proximo"

        resultados.append({
            "tipo_id": tipo_id,
            "nombre": nombre,
            "categoria": categoria,
            "clase": clase,
            "estado": estado,
            "km_restante": km_restante,
            "dias_restantes": dias_restantes,
            "intervalo_km": intervalo_km,
            "intervalo_meses": intervalo_meses,
        })

    # Ordenamos: primero lo más urgente (menos km restantes).
    def clave_orden(r):
        return r["km_restante"] if r["km_restante"] is not None else 9_999_999
    resultados.sort(key=clave_orden)
    return resultados


def calcular_estado_vehiculo(vehiculo: dict) -> list[dict]:
    """
    Devuelve una lista con el estado de cada control del vehículo.
    Cada elemento tiene: nombre, categoria, estado, km_restante, texto.

    Lee los datos y delega el cálculo en `calcular_estado`. Es el único punto de
    este módulo que toca la base de datos, para que el cálculo siga siendo puro.
    """
    return calcular_estado(
        vehiculo,
        db.listar_tipos_mantenimiento(),
        db.historial(vehiculo["id"], 500),
        db.intervalos_de_variante(vehiculo["variante_id"]),
    )


def emoji_estado(estado: str) -> str:
    return {"vencido": "🔴", "proximo": "🟡", "al_dia": "🟢"}.get(estado, "⚪")


def texto_estado(resultado: dict) -> str:
    """Arma una línea legible para un control, ej: '🟡 Filtro de aire — faltan 300 km'."""
    emoji = emoji_estado(resultado["estado"])
    nombre = resultado["nombre"]
    km = resultado["km_restante"]
    if km is None:
        detalle = "sin datos de kilometraje"
    elif km <= 0:
        detalle = f"<b>vencido</b> (excedido por {abs(km)} km)"
    else:
        detalle = f"faltan {km} km"
    return f"{emoji} {nombre} — {detalle}"
