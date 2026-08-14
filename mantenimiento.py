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


def calcular_estado_vehiculo(vehiculo: dict) -> list[dict]:
    """
    Devuelve una lista con el estado de cada control del vehículo.
    Cada elemento tiene: nombre, categoria, estado, km_restante, texto.
    """
    variante_id = vehiculo["variante_id"]
    km_actual = vehiculo.get("kilometraje_actual") or 0

    # Diccionario id_tipo -> nombre para mostrar bonito.
    tipos = {t["id"]: t for t in db.listar_tipos_mantenimiento()}

    resultados = []
    for intervalo in db.intervalos_de_variante(variante_id):
        tipo_id = intervalo["tipo_mantenimiento_id"]
        tipo = tipos.get(tipo_id, {})
        nombre = tipo.get("nombre", f"Control {tipo_id}")
        categoria = tipo.get("categoria", "")

        intervalo_km = intervalo.get("intervalo_km")
        intervalo_meses = intervalo.get("intervalo_meses")

        # ¿Cuándo se hizo por última vez?
        ultimo = db.ultimo_mantenimiento(vehiculo["id"], tipo_id)
        if ultimo:
            km_base = ultimo.get("kilometraje") or 0
            fecha_base = _a_fecha(ultimo.get("fecha"))
        else:
            # Nunca registrado: partimos del estado actual del vehículo.
            km_base = 0
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
            dias_restantes = proximo_dia - date.today().toordinal()

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
            "estado": estado,
            "km_restante": km_restante,
            "dias_restantes": dias_restantes,
            "intervalo_km": intervalo_km,
        })

    # Ordenamos: primero lo más urgente (menos km restantes).
    def clave_orden(r):
        return r["km_restante"] if r["km_restante"] is not None else 9_999_999
    resultados.sort(key=clave_orden)
    return resultados


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
