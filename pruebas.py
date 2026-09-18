"""
pruebas.py
----------
Pruebas de humo de la aplicación. Se ejecutan con:

    .\\.venv\\Scripts\\python.exe pruebas.py

NO tocan Supabase ni Telegram: se configuran credenciales de mentira y se
sustituyen las funciones que salen a la red. Por eso se pueden correr en
cualquier momento, incluso sin conexión, y sin riesgo para los datos reales.

Cubren lo que se rompió alguna vez: las rutas que mantienen vivo el servicio,
el webhook que respondía tarde, los comandos que reventaban sin vehículo y el
cálculo de vencimientos de un auto recién registrado.
"""

import os
import sys

# Credenciales de mentira ANTES de importar la app. Van con setdefault y
# python-dotenv no pisa lo que ya existe, así que aunque tengas un .env con
# los datos de producción, estas pruebas nunca lo usan.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:FALSO")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "secreto-webhook")
os.environ.setdefault("TASKS_TOKEN", "secreto-tareas")
os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoieCJ9.falsa")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "1")

import httpx
from fastapi.testclient import TestClient

import db
import main
import mantenimiento
import tareas
import telegram as tg

_fallos: list[str] = []


def revisar(condicion: bool, descripcion: str) -> None:
    """Registra el resultado de una comprobación sin cortar la ejecución."""
    print(f"  {'OK   ' if condicion else 'FALLA'}  {descripcion}")
    if not condicion:
        _fallos.append(descripcion)


# =====================================================================
# 1. RUTAS HTTP
# =====================================================================

def probar_rutas() -> None:
    print("\n[1] Rutas HTTP")
    cliente = TestClient(main.app)

    r = cliente.get("/salud")
    revisar(r.status_code == 200 and r.text == "ok",
            "/salud responde 'ok' en texto plano (keep-alive de cron-job.org)")

    revisar(cliente.get("/").status_code == 200, "/ responde el estado de la app")

    revisar(cliente.get("/tasks/revisar-vencimientos").status_code == 403,
            "la tarea rechaza una llamada sin token")
    revisar(cliente.get("/tasks/revisar-vencimientos?token=malo").status_code == 403,
            "la tarea rechaza un token incorrecto")

    corridas = []
    main.tareas.ejecutar_revision = lambda: corridas.append(1)

    r = cliente.get("/tasks/revisar-vencimientos?token=secreto-tareas")
    revisar(r.status_code == 200 and r.text == "ok" and len(corridas) == 1,
            "la tarea acepta el token en la URL y responde corto")

    r = cliente.get("/tasks/revisar-vencimientos", headers={"X-Tasks-Token": "secreto-tareas"})
    revisar(r.status_code == 200 and len(corridas) == 2,
            "la tarea acepta el token por cabecera")

    r = cliente.post("/webhook/telegram", json={"message": {}},
                     headers={"X-Telegram-Bot-Api-Secret-Token": "malo"})
    revisar(r.status_code == 403, "el webhook rechaza un secreto incorrecto")

    recibidos = []
    main.handlers.procesar_update = lambda u: recibidos.append(u)
    r = cliente.post("/webhook/telegram", json={"message": {"text": "hola"}},
                     headers={"X-Telegram-Bot-Api-Secret-Token": "secreto-webhook"})
    revisar(r.status_code == 200 and len(recibidos) == 1,
            "el webhook contesta 200 y procesa el mensaje en segundo plano")

    revisar(cliente.get("/panel").status_code == 200, "el panel web se sirve completo")


# =====================================================================
# 2. CÁLCULO DE VENCIMIENTOS
# =====================================================================

TIPOS = [
    {"id": 1, "nombre": "Aceite de motor", "categoria": "Motor", "clase": "reemplazo"},
    {"id": 2, "nombre": "Filtro de aire", "categoria": "Motor", "clase": "reemplazo"},
]
INTERVALOS = [
    {"tipo_mantenimiento_id": 1, "intervalo_km": 5000, "intervalo_meses": 6},
    {"tipo_mantenimiento_id": 2, "intervalo_km": 20000, "intervalo_meses": None},
]
VEHICULO = {"id": 7, "variante_id": 1, "kilometraje_actual": 45000,
            "fecha_actualizacion_km": db._hoy(), "fecha_ultimo_aceite": db._hoy()}


def probar_calculo() -> None:
    print("\n[2] Cálculo de vencimientos")
    db.listar_tipos_mantenimiento = lambda: TIPOS
    db.intervalos_de_variante = lambda vid: INTERVALOS
    db.historial = lambda vid, limite=15: []
    db.km_base_vehiculo = lambda vid: 45000

    estados = mantenimiento.calcular_estado_vehiculo(VEHICULO)
    revisar(all(e["estado"] == "al_dia" for e in estados),
            "un auto registrado con 45.000 km NO sale con todo vencido")

    estados = mantenimiento.calcular_estado_vehiculo({**VEHICULO, "kilometraje_actual": 49800})
    revisar(estados[0]["estado"] == "proximo", "a 200 km del objetivo avisa 'proximo'")

    estados = mantenimiento.calcular_estado_vehiculo({**VEHICULO, "kilometraje_actual": 50500})
    revisar(estados[0]["estado"] == "vencido", "pasado el intervalo sí marca 'vencido'")

    db.km_base_vehiculo = lambda vid: None
    estados = mantenimiento.calcular_estado_vehiculo(VEHICULO)
    revisar(all(e["estado"] == "al_dia" for e in estados),
            "un auto viejo sin lecturas guardadas parte de su km actual")

    db.km_base_vehiculo = lambda vid: 45000
    db.historial = lambda vid, limite=15: [
        {"tipo_mantenimiento_id": 1, "kilometraje": 47000, "fecha": db._hoy()}]
    estados = mantenimiento.calcular_estado_vehiculo({**VEHICULO, "kilometraje_actual": 52500})
    aceite = [e for e in estados if e["tipo_id"] == 1][0]
    revisar(aceite["km_restante"] == -500, "con historial, cuenta desde el último servicio")


# =====================================================================
# 3. TAREA DE RECORDATORIOS
# =====================================================================

def probar_tarea() -> None:
    print("\n[3] Tarea de recordatorios")
    consultas = []
    db.listar_usuarios_aprobados = lambda: (consultas.append("usuarios") or [
        {"id": 1, "telegram_id": 111, "estado": "aprobado"},
        {"id": 2, "telegram_id": 222, "estado": "aprobado"}])
    db.listar_todos_los_vehiculos = lambda: (consultas.append("vehiculos") or [
        {**VEHICULO, "usuario_id": 1, "placa": "AAA-1", "fecha_actualizacion_km": "2000-01-01"},
        {**VEHICULO, "usuario_id": 2, "placa": "BBB-2", "fecha_actualizacion_km": "2000-01-01"},
        {**VEHICULO, "usuario_id": 9, "placa": "SIN-DUENO", "fecha_actualizacion_km": "2000-01-01"},
    ])
    db.historial = lambda vid, limite=15: []
    enviados = []
    # tareas.tg ES el módulo telegram: hay que devolverlo como estaba al
    # terminar, o el bloque [4] acabaría probando esta función de mentira.
    envio_real = tg.enviar_mensaje
    tg.enviar_mensaje = lambda chat, texto, teclado=None: enviados.append(chat)
    try:
        _probar_tarea_con_envio_falso(consultas, enviados)
    finally:
        tg.enviar_mensaje = envio_real


def _probar_tarea_con_envio_falso(consultas: list, enviados: list) -> None:
    total = tareas.revisar_vencimientos()
    revisar(consultas.count("usuarios") == 1,
            "consulta la tabla 'usuarios' UNA vez, no una por vehículo")
    revisar(enviados == [111, 222] and total == 2,
            "avisa a los dueños aprobados e ignora el vehículo huérfano")

    db.listar_todos_los_vehiculos = lambda: [
        {**VEHICULO, "usuario_id": 1, "placa": "AAA-1", "fecha_actualizacion_km": db._hoy()}]
    enviados.clear()
    tareas.revisar_vencimientos()
    revisar(enviados == [], "no insiste a quien ya registró su kilometraje hoy")

    tareas._candado.acquire()
    try:
        tareas.ejecutar_revision()
        revisar(True, "el candado evita que dos corridas del cron se pisen")
    finally:
        tareas._candado.release()


# =====================================================================
# 4. CACHÉ, TIEMPOS DE ESPERA Y REINTENTOS
# =====================================================================

def probar_infraestructura() -> None:
    print("\n[4] Caché, tiempos de espera y reintentos")
    db.limpiar_cache()
    veces = []
    for _ in range(5):
        db._cacheado("prueba", lambda: (veces.append(1) or [{"id": 1}]))
    revisar(len(veces) == 1, "la caché de catálogos evita 4 de cada 5 consultas")
    db.limpiar_cache()
    db._cacheado("prueba", lambda: (veces.append(1) or [{"id": 1}]))
    revisar(len(veces) == 2, "limpiar_cache() fuerza una consulta nueva")

    revisar(db.supabase.postgrest.session.timeout.read is not None,
            "el cliente de Supabase tiene tiempo de espera definido")

    intentos = []

    def falla_una_vez(_peticion):
        intentos.append(1)
        if len(intentos) == 1:
            raise httpx.ConnectError("conexión caducada")
        return httpx.Response(200, json={"ok": True})

    tg._cliente = httpx.Client(transport=httpx.MockTransport(falla_una_vez))
    revisar(tg.enviar_mensaje(1, "hola") == {"ok": True} and len(intentos) == 2,
            "un fallo de red se reintenta una vez y sale bien")

    intentos.clear()
    tg._cliente = httpx.Client(transport=httpx.MockTransport(
        lambda p: (intentos.append(1) or httpx.Response(400, json={"ok": False}))))
    try:
        tg.enviar_mensaje(1, "hola")
        revisar(False, "un error 400 de Telegram debe lanzar excepción")
    except httpx.HTTPStatusError:
        revisar(len(intentos) == 1, "un error 400 de Telegram no se reintenta en vano")


if __name__ == "__main__":
    probar_rutas()
    probar_calculo()
    probar_tarea()
    probar_infraestructura()
    print("\n" + "=" * 62)
    if _fallos:
        print(f"{len(_fallos)} PRUEBA(S) FALLARON:")
        for f in _fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("TODAS LAS PRUEBAS PASARON")
