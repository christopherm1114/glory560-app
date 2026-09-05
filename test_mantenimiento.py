"""
test_mantenimiento.py
---------------------
Pruebas del motor de cálculo. No tocan la base de datos ni la red: `calcular_estado`
recibe los datos ya leídos, así que aquí se le pasan diccionarios inventados.

La fecha también se pasa como argumento (`hoy=`), para que una prueba que hoy pasa
no empiece a fallar el mes que viene.
"""

from datetime import date

import mantenimiento


# --- Datos de apoyo -------------------------------------------------------

TIPOS = [
    {"id": 1, "nombre": "Aceite de motor", "categoria": "Motor", "clase": "reemplazo"},
    {"id": 2, "nombre": "Filtro de aire", "categoria": "Motor", "clase": "reemplazo"},
]

# 5.000 km para el aceite; 10.000 km o 12 meses para el filtro.
INTERVALOS = [
    {"tipo_mantenimiento_id": 1, "intervalo_km": 5_000, "intervalo_meses": None},
    {"tipo_mantenimiento_id": 2, "intervalo_km": 10_000, "intervalo_meses": 12},
]


def vehiculo(km_actual, km_inicial=None, **extra):
    v = {"id": 1, "variante_id": 1, "kilometraje_actual": km_actual}
    if km_inicial is not None:
        v["kilometraje_inicial"] = km_inicial
    v.update(extra)
    return v


def estado_de(resultados, tipo_id):
    return next(r for r in resultados if r["tipo_id"] == tipo_id)


# --- Problema 6: vehículo sin historial ------------------------------------

def test_vehiculo_nuevo_sin_historial_no_aparece_vencido():
    """
    El caso que motivó el arreglo: un vehículo dado de alta con 45.000 km no
    tiene historial de ningún control, y antes salía todo en rojo el primer día.
    """
    v = vehiculo(km_actual=45_000, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 1)["estado"] == "al_dia"
    assert estado_de(r, 2)["estado"] == "al_dia"


def test_la_linea_base_es_el_alta_y_no_se_mueve_con_el_odometro():
    """
    La distinción que justifica la columna `kilometraje_inicial`: si la base
    fuera el kilometraje actual, faltarían siempre 5.000 km y el control no
    vencería nunca. Al ser el del alta, la distancia se va acortando.
    """
    alta = 45_000
    faltantes = []
    for km_hoy in (45_000, 47_000, 49_000):
        v = vehiculo(km_actual=km_hoy, km_inicial=alta)
        r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))
        faltantes.append(estado_de(r, 1)["km_restante"])

    assert faltantes == [5_000, 3_000, 1_000]


def test_control_nunca_registrado_termina_venciendo():
    """Recorrido el intervalo completo desde el alta, el control vence."""
    v = vehiculo(km_actual=50_100, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 1)["estado"] == "vencido"
    assert estado_de(r, 1)["km_restante"] == -100


def test_vehiculo_anterior_a_la_migracion_usa_el_km_actual():
    """
    Compatibilidad: las filas creadas antes de la migración 002 no tienen
    `kilometraje_inicial`. No deben caer en el comportamiento viejo (base 0,
    todo vencido), sino aproximar con el kilometraje actual.
    """
    v = vehiculo(km_actual=45_000)   # sin kilometraje_inicial
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 1)["estado"] == "al_dia"


# --- Cálculo con historial -------------------------------------------------

def test_se_mide_desde_el_ultimo_servicio_registrado():
    historial = [{"tipo_mantenimiento_id": 1, "kilometraje": 48_000, "fecha": "2025-06-01"}]
    v = vehiculo(km_actual=50_000, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, historial, INTERVALOS, hoy=date(2026, 1, 1))

    # 48.000 + 5.000 - 50.000 = 3.000, no 45.000 + 5.000 - 50.000.
    assert estado_de(r, 1)["km_restante"] == 3_000


def test_entre_varios_servicios_manda_el_de_mayor_kilometraje():
    """El historial no llega ordenado; se toma el más avanzado, no el último."""
    historial = [
        {"tipo_mantenimiento_id": 1, "kilometraje": 48_000, "fecha": "2025-06-01"},
        {"tipo_mantenimiento_id": 1, "kilometraje": 46_000, "fecha": "2025-01-01"},
    ]
    v = vehiculo(km_actual=50_000, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, historial, INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 1)["km_restante"] == 3_000


def test_umbral_de_aviso_marca_proximo():
    """A 500 km o menos (KM_AVISO) el control pasa a 'proximo', no a 'vencido'."""
    v = vehiculo(km_actual=49_700, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 1)["km_restante"] == 300
    assert estado_de(r, 1)["estado"] == "proximo"


# --- Vencimiento por tiempo ------------------------------------------------

def test_vence_por_tiempo_aunque_sobren_kilometros():
    """
    El filtro tiene 10.000 km o 12 meses: manda lo que se cumpla primero. Con
    pocos km recorridos pero la fecha pasada, debe salir vencido igual.
    """
    v = vehiculo(km_actual=45_500, km_inicial=45_000, fecha_ultimo_aceite="2024-01-01")
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    filtro = estado_de(r, 2)
    assert filtro["km_restante"] == 9_500      # por kilometraje iría sobrado
    assert filtro["estado"] == "vencido"       # pero el tiempo ya se cumplió


def test_sin_fecha_de_referencia_no_se_evalua_el_tiempo():
    v = vehiculo(km_actual=45_500, km_inicial=45_000)   # sin fechas
    r = mantenimiento.calcular_estado(v, TIPOS, [], INTERVALOS, hoy=date(2026, 1, 1))

    assert estado_de(r, 2)["dias_restantes"] is None
    assert estado_de(r, 2)["estado"] == "al_dia"


# --- Orden y presentación --------------------------------------------------

def test_lo_mas_urgente_va_primero():
    historial = [{"tipo_mantenimiento_id": 2, "kilometraje": 45_000, "fecha": "2025-12-01"}]
    v = vehiculo(km_actual=49_900, km_inicial=45_000)
    r = mantenimiento.calcular_estado(v, TIPOS, historial, INTERVALOS, hoy=date(2026, 1, 1))

    assert [x["tipo_id"] for x in r] == [1, 2]
    assert r[0]["km_restante"] <= r[1]["km_restante"]


def test_texto_estado_describe_el_exceso_cuando_esta_vencido():
    linea = mantenimiento.texto_estado(
        {"estado": "vencido", "nombre": "Aceite de motor", "km_restante": -100}
    )
    assert "Aceite de motor" in linea
    assert "100" in linea


def test_el_envoltorio_lee_los_datos_y_delega_el_calculo(monkeypatch):
    """
    `calcular_estado_vehiculo` es lo que llaman el panel, el bot y la tarea de
    recordatorios. Esta prueba fija su contrato: que consulte lo que corresponde
    y que el resultado sea el mismo que el del cálculo puro.
    """
    import db

    llamadas = {}
    monkeypatch.setattr(db, "listar_tipos_mantenimiento", lambda: (llamadas.setdefault("tipos", True), TIPOS)[1])
    monkeypatch.setattr(db, "historial", lambda vid, lim: (llamadas.setdefault("historial", (vid, lim)), [])[1])
    monkeypatch.setattr(db, "intervalos_de_variante", lambda var: (llamadas.setdefault("intervalos", var), INTERVALOS)[1])

    v = vehiculo(km_actual=45_000, km_inicial=45_000)
    r = mantenimiento.calcular_estado_vehiculo(v)

    assert llamadas["historial"][0] == v["id"]
    assert llamadas["intervalos"] == v["variante_id"]
    assert [x["tipo_id"] for x in r] == [1, 2]
    assert estado_de(r, 1)["estado"] == "al_dia"


def test_a_fecha_acepta_formato_valido_y_descarta_basura():
    assert mantenimiento._a_fecha("2025-06-01") == date(2025, 6, 1)
    assert mantenimiento._a_fecha(None) is None
    assert mantenimiento._a_fecha("no es una fecha") is None
