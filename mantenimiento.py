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


# Tope de cordura: ningún odómetro de un Glory 560 va a marcar esto.
# Sirve para atajar un dígito de más antes de que ensucie el historial.
KM_MAXIMO_RAZONABLE = 2_000_000


def validar_lectura_km(km_nuevo, km_actual) -> tuple[bool, str]:
    """
    Valida una LECTURA del odómetro (el número que el usuario reporta hoy).

    Devuelve (aceptada, motivo). El motivo va dirigido al usuario, en texto
    plano: el dominio no sabe si lo leerá Telegram o el panel.

    Un odómetro no retrocede. Aceptar un valor menor al que ya está guardado
    es cómo se ensuciaron los datos de producción: quedan lecturas de 46.000
    entre valores de 232.000, y esa cifra suelta se volvía la línea base de
    los cálculos, dejando el vehículo entero en rojo.
    """
    if km_nuevo is None or not isinstance(km_nuevo, int):
        return False, "El kilometraje debe ser un número entero."
    if km_nuevo <= 0:
        return False, "El kilometraje debe ser mayor que cero."
    if km_nuevo > KM_MAXIMO_RAZONABLE:
        return False, (f"{km_nuevo:,} km no parece un valor real. "
                       "Revisa si se te fue un dígito de más.").replace(",", ".")
    actual = km_actual or 0
    if km_nuevo < actual:
        return False, (f"El odómetro no puede retroceder: ya tienes registrados "
                       f"{actual:,} km y escribiste {km_nuevo:,}. Si el dato guardado "
                       "es el equivocado, corrígelo desde /perfil.").replace(",", ".")
    return True, ""


def validar_km_servicio(km_servicio, km_actual) -> tuple[bool, str]:
    """
    Valida el kilometraje de un SERVICIO que se registra en el historial.

    A diferencia de una lectura, aquí sí es normal un valor menor al odómetro
    actual: se puede registrar hoy un cambio de aceite hecho hace meses. Lo
    que no puede es ser MAYOR que el odómetro — eso significa un servicio en
    el futuro, y el motor de cálculo lo toma como línea base, dejando ese
    control en verde para siempre. En producción hay un caso así: un servicio
    a 105.000 km en un vehículo cuyo odómetro marca 47.300.
    """
    if km_servicio is None or not isinstance(km_servicio, int):
        return False, "El kilometraje debe ser un número entero."
    if km_servicio <= 0:
        return False, "El kilometraje debe ser mayor que cero."
    if km_servicio > KM_MAXIMO_RAZONABLE:
        return False, (f"{km_servicio:,} km no parece un valor real. "
                       "Revisa si se te fue un dígito de más.").replace(",", ".")
    actual = km_actual or 0
    if actual and km_servicio > actual:
        return False, (f"El servicio no puede ser a más kilómetros que el odómetro: "
                       f"tu vehículo marca {actual:,} km. Si ya avanzaste, registra "
                       "primero la lectura nueva con /km.").replace(",", ".")
    return True, ""


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

    # Diccionario id_tipo -> tipo (para nombre, categoría, clase).
    tipos = {t["id"]: t for t in db.listar_tipos_mantenimiento()}

    # Línea base: el kilometraje con el que el vehículo entró al sistema.
    # Los controles que nunca se han registrado se cuentan DESDE ahí, no desde
    # cero. Un auto que se registra con 45.000 km y un intervalo de 5.000 km
    # tiene su primer aviso a los 50.000, no todo en rojo el primer día.
    # Si el vehículo es viejo y no tiene lecturas guardadas, arrancamos desde
    # su kilometraje actual: se corrige solo en cuanto registre un /km.
    km_inicial = db.km_base_vehiculo(vehiculo["id"])
    if km_inicial is None:
        km_inicial = km_actual

    # Traemos TODOS los mantenimientos del vehículo de una sola vez (en lugar de
    # una consulta por cada control) y guardamos el ÚLTIMO de cada tipo por km.
    ultimos: dict = {}
    for m in db.historial(vehiculo["id"], 500):
        tid = m["tipo_mantenimiento_id"]
        prev = ultimos.get(tid)
        if prev is None or (m.get("kilometraje") or 0) > (prev.get("kilometraje") or 0):
            ultimos[tid] = m

    resultados = []
    for intervalo in db.intervalos_de_variante(variante_id):
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
            # Nunca registrado: partimos de la línea base del vehículo.
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
