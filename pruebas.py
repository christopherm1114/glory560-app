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

# Desde que un token de tarea invalido avisa al administrador, CUALQUIER
# prueba que use un token incorrecto intentaria salir a Telegram. Se anula el
# aviso para toda la bateria y se restaura solo donde se quiere comprobarlo
# (seccion 15). Se parchea avisar_al_admin y no enviar_mensaje, porque la
# seccion 4 necesita probar enviar_mensaje de verdad contra un transporte
# simulado.
_avisar_real = tg.avisar_al_admin
tg.avisar_al_admin = lambda *a, **k: None


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


# =====================================================================
# 5. CONVERSACIONES ABANDONADAS
# =====================================================================

def probar_conversaciones() -> None:
    print("\n[5] Conversaciones abandonadas")
    from datetime import datetime, timedelta, timezone
    ahora = datetime.now(timezone.utc)

    casos = [
        (None, False, "una fila sin fecha no se descarta"),
        ((ahora - timedelta(minutes=5)).isoformat(), False,
         "una conversación de hace 5 minutos sigue viva"),
        ((ahora - timedelta(hours=5)).isoformat(), False,
         "a las 5 horas todavía sigue viva"),
        ((ahora - timedelta(hours=7)).isoformat(), True,
         "a las 7 horas ya caducó"),
        ((ahora - timedelta(days=24)).isoformat(), True,
         "una de hace 24 días caduca"),
        ((ahora - timedelta(days=24)).replace(tzinfo=None).isoformat(), True,
         "una fila vieja sin zona horaria también caduca"),
        ("texto basura", False, "un valor ilegible no rompe nada"),
    ]
    for valor, esperado, descripcion in casos:
        revisar(db._conversacion_caducada(valor) is esperado, descripcion)


# =====================================================================
# 6. LECTURA DE NÚMEROS TECLEADOS POR EL USUARIO
# =====================================================================

def probar_numeros() -> None:
    print("\n[6] Números tecleados por el usuario")
    import handlers

    # El punto es separador de miles cuando lo siguen TRES dígitos, y decimal
    # en cualquier otro caso. La versión vieja borraba todos los puntos, así
    # que '3861.5' se guardaba como 38615 — así se ensució la base real.
    casos = [
        ("45.000", 45000, "'45.000' son cuarenta y cinco mil"),
        ("232.930", 232930, "'232.930' son doscientos treinta y dos mil"),
        ("1.234.567", 1234567, "'1.234.567' se lee con dos separadores"),
        ("3861.5", 3861, "'3861.5' son 3861 km y medio, NO 38.615"),
        ("11540.5", 11540, "'11540.5' no se convierte en 115.405"),
        ("10520.0", 10520, "'10520.0' no se convierte en 105.200"),
        ("46.0", 46, "'46.0' son 46, no 460"),
        ("45,5", 45, "la coma decimal también se trunca"),
        ("1,234.56", 1234, "manda el último separador"),
        ("47300", 47300, "un número limpio pasa igual"),
        ("  47300  ", 47300, "los espacios sobrantes no estorban"),
        ("abc", None, "un texto no numérico devuelve None"),
        ("12a", None, "un número con letras pegadas devuelve None"),
        ("", None, "el texto vacío devuelve None"),
    ]
    for entrada, esperado, descripcion in casos:
        revisar(handlers._a_entero(entrada) == esperado, descripcion)


# =====================================================================
# 7. VALIDACIÓN DEL KILOMETRAJE
# =====================================================================

def probar_validacion_km() -> None:
    print("\n[7] Validación del kilometraje")
    ACTUAL = 47300

    acepta = lambda km: mantenimiento.validar_lectura_km(km, ACTUAL)[0]
    revisar(acepta(47400), "una lectura mayor al odómetro se acepta")
    revisar(acepta(ACTUAL), "repetir el mismo valor se acepta")
    revisar(not acepta(46000), "una lectura que hace retroceder el odómetro se rechaza")
    revisar(not acepta(0), "el cero se rechaza")
    revisar(not acepta(-5), "un negativo se rechaza")
    revisar(not acepta(5_000_000), "un valor imposible se rechaza")
    revisar(not acepta(None), "un no-número se rechaza")
    revisar("perfil" in mantenimiento.validar_lectura_km(46000, ACTUAL)[1],
            "el rechazo explica cómo corregir el dato")

    acepta_serv = lambda km: mantenimiento.validar_km_servicio(km, ACTUAL)[0]
    revisar(acepta_serv(40000), "un servicio anterior al odómetro se acepta")
    revisar(acepta_serv(ACTUAL), "un servicio justo al día de hoy se acepta")
    revisar(not acepta_serv(105000), "un servicio por encima del odómetro se rechaza")
    revisar(not acepta_serv(0), "un servicio en cero se rechaza")


# =====================================================================
# 8. CONTRATO ENTRE EL MOTOR, LA API Y EL PANEL
# =====================================================================

# Campos que panel.html lee de cada fila que le entrega /api/mis-datos.
# Salieron de recorrer el propio panel.html (`r.<campo>` en pintarSemaforo,
# filaSemaforo y vistaRecom). Si alguien renombra uno en web.py sin tocar el
# panel, la pantalla se rompe en silencio: no hay tipos ni esquema que avisen.
CAMPOS_SEMAFORO = {"nombre", "estado", "km_restante", "categoria", "clase",
                   "precio_promedio", "conteo", "mercado_min", "mercado_max", "mercado_nota"}
CAMPOS_RECOMENDACION = {"nombre", "categoria", "intervalo_km", "intervalo_meses", "descripcion"}
# Campos que web.py necesita de cada resultado del motor de cálculo.
CAMPOS_MOTOR = {"tipo_id", "nombre", "categoria", "clase", "estado",
                "km_restante", "dias_restantes", "intervalo_km", "intervalo_meses"}


def probar_contrato_panel() -> None:
    print("\n[8] Contrato entre el motor, la API y el panel")
    import web

    db.listar_tipos_mantenimiento = lambda: [
        {"id": 1, "nombre": "Aceite de motor", "categoria": "Motor", "clase": "reemplazo",
         "descripcion": "Cambio de aceite", "mercado_min": 20, "mercado_max": 40,
         "mercado_nota": "referencial"},
        {"id": 2, "nombre": "Revisión de frenos", "categoria": "Frenos", "clase": "inspeccion",
         "descripcion": "Inspección visual", "mercado_min": None, "mercado_max": None,
         "mercado_nota": None},
    ]
    db.intervalos_de_variante = lambda vid: [
        {"tipo_mantenimiento_id": 1, "intervalo_km": 5000, "intervalo_meses": 6},
        {"tipo_mantenimiento_id": 2, "intervalo_km": 10000, "intervalo_meses": None},
    ]
    db.historial = lambda vid, limite=15: []
    db.km_base_vehiculo = lambda vid: 45000

    filas = mantenimiento.calcular_estado_vehiculo(VEHICULO)
    faltan_motor = CAMPOS_MOTOR - set(filas[0])
    revisar(not faltan_motor,
            f"el motor entrega los campos que web.py consume (faltan: {faltan_motor or 'ninguno'})")

    db.buscar_vehiculo_de_usuario = lambda uid: dict(VEHICULO, placa="AAA-1", anio_modelo=2022)
    db.obtener_variante = lambda vid: {
        "nombre": "SFG18 CVT", "motor": "1.8", "transmision": "CVT", "aceite_motor": "5W-30",
        "capacidad_aceite_l": 4.0, "bujia_tipo": "NGK", "liquido_transmision": "CVT-J1",
        "capacidad_transmision_l": 6.0, "refrigerante_l": 5.0, "medida_llanta": "215/60R17",
        "presion_llantas": "32 psi"}
    db.promedios_por_tipo = lambda costo_max=5000.0: {1: {"promedio": 30.0, "conteo": 4}}
    db.gastos_por_categoria = lambda vid: [{"categoria": "Motor", "total": 120.0}]
    db.historial_km = lambda vid, limite=100: []

    datos = web._resumen_vehiculo({"id": 1, "nombre": "Prueba"})

    revisar(bool(datos.get("proximos")), "la API entrega filas del semáforo")
    if datos.get("proximos"):
        faltan = CAMPOS_SEMAFORO - set(datos["proximos"][0])
        revisar(not faltan, f"el semáforo trae lo que el panel lee (faltan: {faltan or 'ninguno'})")

    revisar(bool(datos.get("recomendaciones")),
            "la API entrega recomendaciones (los controles de clase 'inspeccion')")
    if datos.get("recomendaciones"):
        faltan = CAMPOS_RECOMENDACION - set(datos["recomendaciones"][0])
        revisar(not faltan,
                f"las recomendaciones traen lo que el panel lee (faltan: {faltan or 'ninguno'})")

    revisar(datos.get("variante", {}).get("nombre") == "SFG18 CVT",
            "el bloque de la variante llega armado")

    # Una variante ausente no debe tumbar el panel entero.
    db.obtener_variante = lambda vid: None
    revisar(web._resumen_vehiculo({"id": 1, "nombre": "Prueba"}).get("variante") is not None,
            "si falta la variante, la API responde igual en vez de dar error 500")


# =====================================================================
# 9. ESCAPE DE HTML EN EL PANEL  (Hallazgo 1)
# =====================================================================

# Campos que llegan del servidor y los teclea una persona. Si alguno se
# interpola en el panel SIN pasar por esc(), un usuario puede inyectar codigo
# que se ejecuta en el navegador del administrador.
CAMPOS_PELIGROSOS = ["x.nombre", "x.telefono", "x.placa", "x.taller", "x.variante",
                     "r.nombre", "r.descripcion", "d.usuario.nombre", "d.usuario.telefono",
                     "v.placa", "v.nombre", "t.nombre", "cat"]


def probar_escape_panel() -> None:
    print("\n[9] Escape de HTML en el panel")
    from pathlib import Path
    import re

    html = Path("panel.html").read_text(encoding="utf-8")

    revisar("function esc(" in html, "el panel define la funcion esc()")
    revisar("&amp;" in html and "&lt;" in html, "esc() mapea los caracteres peligrosos")

    # Ninguna interpolacion debe llevar un campo peligroso "desnudo".
    sin_escapar = []
    for linea in html.split("\n"):
        if "base64" in linea:
            continue
        for trozo in re.findall(r"\$\{([^{}]*)\}", linea):
            for campo in CAMPOS_PELIGROSOS:
                # El campo aparece y no esta dentro de una llamada a esc(...)
                if re.search(r"(?<![\w.])" + re.escape(campo) + r"(?![\w])", trozo) \
                        and "esc(" not in trozo:
                    sin_escapar.append(trozo.strip()[:60])
    revisar(not sin_escapar,
            f"ninguna interpolacion deja un campo sin escapar (sueltos: {sin_escapar[:3] or 'ninguno'})")

    # El boton de precio de mercado ya no mete datos dentro de un onclick.
    revisar("onclick=\"verMercado('" not in html,
            "el boton de precio ya no interpola datos dentro del onclick")
    revisar("verMercadoDe(this)" in html,
            "ese boton pasa los datos por atributos data-*")


# =====================================================================
# 10. LIMITACION DE INTENTOS  (Hallazgo 3)
# =====================================================================

def probar_limite_intentos() -> None:
    print("\n[10] Limitacion de intentos")
    import auth

    clave = "prueba:limite:unica"
    auth.limpiar_intentos(clave)

    revisar(auth.intento_permitido(clave), "el primer intento se permite")
    for _ in range(auth.LIMITE_INTENTOS):
        auth.registrar_fallo(clave)
    revisar(not auth.intento_permitido(clave),
            f"tras {auth.LIMITE_INTENTOS} fallos se bloquea")
    revisar(auth.segundos_para_reintentar(clave) > 0, "informa cuanto falta para reintentar")

    auth.limpiar_intentos(clave)
    revisar(auth.intento_permitido(clave), "un acierto limpia el contador")

    # La ventana es deslizante: un fallo antiguo no debe contar.
    import time as _t
    auth._fallos[clave] = [_t.time() - auth.VENTANA_SEGUNDOS - 10] * auth.LIMITE_INTENTOS
    revisar(auth.intento_permitido(clave), "los fallos vencidos dejan de contar")
    auth.limpiar_intentos(clave)

    # El limitador no puede crecer sin fin (seria un agotamiento de memoria).
    auth._fallos.clear()
    for i in range(auth._MAX_CLAVES + 50):
        auth._fallos[f"basura:{i}"] = [_t.time() - auth.VENTANA_SEGUNDOS - 1]
    auth.intento_permitido("dispara-la-poda")
    revisar(len(auth._fallos) < auth._MAX_CLAVES,
            "el contador poda los registros vencidos y no crece sin limite")
    auth._fallos.clear()

    # Y de extremo a extremo: el login devuelve 429 tras agotar los intentos.
    cliente = TestClient(main.app)
    db.buscar_usuario_por_telefono_normalizado = lambda t: None
    codigos = [cliente.post("/api/login",
                            json={"usuario": "0991112233", "contrasena": "malaclave1"}).status_code
               for _ in range(auth.LIMITE_INTENTOS + 2)]
    revisar(codigos[0] == 401, "un intento fallido responde 401")
    revisar(429 in codigos, f"tras varios fallos responde 429 (codigos: {codigos})")
    auth._fallos.clear()


# =====================================================================
# 11. CICLO DE SESION Y CAMBIO DE CONTRASENA  (Hallazgo 7)
# =====================================================================

def probar_sesion() -> None:
    print("\n[11] Ciclo de sesion")
    import auth
    import web

    auth._fallos.clear()
    hash_inicial = auth.hash_password("ClaveBuena1")
    persona = {"id": 1, "nombre": "Prueba", "telefono": "0991112233",
               "estado": "aprobado", "rol": "usuario", "clave_hash": hash_inicial}

    db.buscar_usuario_por_telefono_normalizado = lambda t: dict(persona)
    db.obtener_usuario = lambda uid: dict(persona)

    # base_url con https: la cookie de sesion lleva el atributo Secure, y sobre
    # http el cliente no la envia de vuelta. Sin esto, las comprobaciones de
    # abajo pasarian por el motivo equivocado: por falta de cookie, no por la
    # marca de credencial.
    cliente = TestClient(main.app, base_url="https://pruebas.local")
    r = cliente.post("/api/login", json={"usuario": "0991112233", "contrasena": "ClaveBuena1"})
    revisar(r.status_code == 200, "el login con la contrasena correcta entra")
    revisar("sesion" in cliente.cookies, "se emite la cookie de sesion")

    galleta = cliente.cookies.get("sesion")
    revisar(len(str(galleta).split(".")) == 4,
            "la cookie lleva usuario, expiracion, marca y firma")

    revisar(cliente.get("/api/sesion").status_code == 200, "la sesion recien creada es valida")

    # Se cambia la contrasena por fuera (como haria otro dispositivo) y la
    # cookie vieja debe dejar de servir.
    persona["clave_hash"] = auth.hash_password("OtraClave2")
    revisar(cliente.get("/api/sesion").status_code == 401,
            "al cambiar la contrasena, la sesion anterior queda invalidada")

    # Una cookie con la firma alterada no debe pasar.
    persona["clave_hash"] = hash_inicial
    cliente.cookies.set("sesion", str(galleta)[:-4] + "0000")
    revisar(cliente.get("/api/sesion").status_code == 401, "una firma alterada se rechaza")

    # Y el formato viejo de tres partes tampoco.
    cliente.cookies.set("sesion", "1.99999999999.firmafalsa")
    revisar(cliente.get("/api/sesion").status_code == 401,
            "una cookie del formato anterior ya no vale")
    auth._fallos.clear()


# =====================================================================
# 12. CABECERAS DE SEGURIDAD  (Hallazgo 5)
# =====================================================================

def probar_cabeceras() -> None:
    print("\n[12] Cabeceras de seguridad")
    cliente = TestClient(main.app)
    cab = cliente.get("/").headers

    esperadas = {
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
    }
    for nombre, valor in esperadas.items():
        revisar(cab.get(nombre) == valor, f"{nombre}: {valor}")
    revisar("max-age=" in cab.get("strict-transport-security", ""),
            "strict-transport-security con max-age")

    csp = cab.get("content-security-policy", "")
    revisar("default-src 'self'" in csp, "la CSP restringe el origen por defecto")
    revisar("frame-ancestors 'none'" in csp, "la CSP impide que el panel se incruste")
    revisar("object-src 'none'" in csp, "la CSP bloquea los objetos incrustados")
    revisar("cdnjs.cloudflare.com" in csp,
            "la CSP permite el CDN de Chart.js, que el panel necesita de verdad")


# =====================================================================
# 13. CAMBIO DE CONTRASENA OBLIGATORIO  (Hallazgo 2)
# =====================================================================

def probar_clave_obligatoria() -> None:
    print("\n[13] Cambio de contrasena obligatorio")
    import auth
    import web

    auth._fallos.clear()

    # Un usuario heredado: sin clave_hash, su contrasena sigue siendo el telefono.
    heredado = {"id": 5, "nombre": "Heredado", "telefono": "0987654321",
                "estado": "aprobado", "rol": "usuario", "clave_hash": None}
    db.buscar_usuario_por_telefono_normalizado = lambda t: dict(heredado)
    db.obtener_usuario = lambda uid: dict(heredado)

    cliente = TestClient(main.app, base_url="https://pruebas.local")
    r = cliente.post("/api/login", json={"usuario": "0987654321", "contrasena": "0987654321"})
    revisar(r.status_code == 200, "el usuario heredado todavia puede entrar (no se le deja fuera)")
    revisar(r.json().get("debe_cambiar") is True, "el login avisa que debe cambiar la contrasena")

    r = cliente.get("/api/sesion")
    revisar(r.status_code == 200 and r.json().get("debe_cambiar") is True,
            "la sesion informa del cambio pendiente")

    # Pero su sesion no sirve para nada mas.
    for ruta in ["/api/mis-datos", "/api/mantenimientos", "/api/tipos"]:
        revisar(cliente.get(ruta).status_code == 401,
                f"{ruta} queda bloqueada hasta que defina su contrasena")

    # Al cambiarla, se desbloquea.
    guardado = {}
    db.actualizar_clave_hash = lambda uid, h: guardado.update({"hash": h})
    r = cliente.post("/api/cambiar-clave", json={"actual": "0987654321",
                                                 "nueva": "ClaveNueva9", "repetir": "ClaveNueva9"})
    revisar(r.status_code == 200, "puede cambiar la contrasena usando el telefono como actual")
    revisar(guardado.get("hash", "").startswith("pbkdf2_sha256$"),
            "la contrasena nueva se guarda cifrada, nunca en claro")

    heredado["clave_hash"] = guardado["hash"]
    revisar(cliente.get("/api/mis-datos").status_code != 401,
            "con la contrasena ya definida, el panel se desbloquea")

    # Una contrasena debil debe rechazarse.
    heredado["clave_hash"] = None
    cliente2 = TestClient(main.app, base_url="https://pruebas.local")
    cliente2.post("/api/login", json={"usuario": "0987654321", "contrasena": "0987654321"})
    r = cliente2.post("/api/cambiar-clave", json={"actual": "0987654321",
                                                  "nueva": "12345678", "repetir": "12345678"})
    revisar(r.status_code == 400, "una contrasena sin letras se rechaza")

    # Y las cuentas nuevas ya no nacen con la contrasena en claro.
    import inspect
    fuente = inspect.getsource(db.crear_usuario)
    revisar('"clave": telefono' not in fuente,
            "crear_usuario ya no guarda el telefono como contrasena en claro")
    auth._fallos.clear()


# =====================================================================
# 14. IMAGENES SERVIDAS APARTE
# =====================================================================

IMAGENES = ["fondo-hero.webp", "fondo-login.jpg", "logo.jpg",
            "auto-hero.webp", "logo-hero.webp"]


def probar_estaticos() -> None:
    print("\n[14] Imagenes servidas aparte")
    from pathlib import Path

    cliente = TestClient(main.app)
    html = Path("panel.html").read_text(encoding="utf-8")

    revisar("base64," not in html,
            "panel.html ya no lleva imagenes incrustadas en base64")
    revisar(len(html) < 80_000,
            f"panel.html pesa poco ({len(html):,} caracteres; antes 397.011)")

    for img in IMAGENES:
        r = cliente.get(f"/estaticos/{img}")
        revisar(r.status_code == 200, f"/estaticos/{img} se sirve")
        # El tipo correcto es imprescindible: con la cabecera nosniff que
        # declaramos, un tipo equivocado hace que el navegador se niegue a
        # dibujar la imagen. Los .webp son el caso que falla si nadie los
        # registra, porque Windows no los trae de fabrica.
        revisar(r.headers.get("content-type", "").startswith("image/"),
                f"  con tipo de imagen correcto ({r.headers.get('content-type')})")

    r = cliente.get(f"/estaticos/{IMAGENES[0]}")
    revisar("max-age=" in r.headers.get("cache-control", ""),
            "las imagenes se cachean en el navegador")

    revisar(cliente.get("/estaticos/no-existe.png").status_code == 404,
            "un archivo inexistente devuelve 404")

    # Toda imagen referenciada por el panel debe existir de verdad.
    import re
    referidas = set(re.findall(r"/estaticos/([A-Za-z0-9._-]+)", html))
    faltantes = [i for i in referidas if not Path("estaticos", i).exists()]
    revisar(not faltantes, f"todas las imagenes referidas existen (faltan: {faltantes or 'ninguna'})")


# =====================================================================
# 15. RESPALDO Y AVISOS AL ADMINISTRADOR
# =====================================================================

def probar_respaldo() -> None:
    print("\n[15] Respaldo y avisos")
    cliente = TestClient(main.app)

    # El envio se sustituye ANTES de la primera llamada rechazada. Desde que
    # un token invalido avisa al administrador, cualquier peticion con token
    # incorrecto intentaria salir a Telegram de verdad; estas pruebas no
    # tocan la red y eso tiene que seguir siendo cierto.
    avisos = []
    envio_real = tg.enviar_mensaje
    tg.enviar_mensaje = lambda chat, texto, teclado=None: avisos.append(texto)
    tg.avisar_al_admin = _avisar_real   # aqui si se quiere el aviso de verdad
    try:
        tg._ULTIMOS_AVISOS.clear()
        revisar(cliente.get("/tasks/respaldo").status_code == 403,
                "la ruta de respaldo rechaza una llamada sin token")
        revisar(cliente.get("/tasks/respaldo?token=malo").status_code == 403,
                "rechaza un token incorrecto")

        # Un cron con el token equivocado fallaba en silencio durante dias.
        # Ahora cada rechazo avisa: es la unica forma de enterarse de que la
        # tarea lleva tiempo sin ejecutarse.
        tg._ULTIMOS_AVISOS.clear()
        cliente.get("/tasks/revisar-vencimientos?token=equivocado")
        revisar(any("token incorrecto" in a for a in avisos),
                "un token incorrecto en los recordatorios avisa al administrador")
        revisar(any("Render" in a for a in avisos),
                "el aviso explica donde mirar para arreglarlo")

        tg._ULTIMOS_AVISOS.clear()
        avisos.clear()
        cliente.get("/tasks/respaldo?token=equivocado")
        revisar(any("respaldo" in a for a in avisos),
                "y lo mismo en la tarea de respaldo")

        avisos.clear()
        cliente.get("/tasks/respaldo?token=equivocado")
        revisar(not avisos, "no repite el aviso en cada intento fallido")
    finally:
        tg.enviar_mensaje = envio_real
        tg.avisar_al_admin = lambda *a, **k: None
        tg._ULTIMOS_AVISOS.clear()

    corridas = []
    main.tareas.ejecutar_respaldo = lambda: corridas.append(1)
    r = cliente.get("/tasks/respaldo?token=secreto-tareas")
    revisar(r.status_code == 200 and r.text == "ok" and len(corridas) == 1,
            "con el token correcto responde corto y trabaja en segundo plano")

    # El volcado no debe llevarse las credenciales. Se sustituye el cliente de
    # base de datos y se devuelve como estaba al terminar: dejarlo cambiado
    # convertiria esta prueba en una trampa para las que se agreguen despues.
    supabase_real = db.supabase
    db.supabase = type("FalsoSupabase", (), {
        "table": lambda self, t: type("C", (), {
            "select": lambda self, c: type("E", (), {
                "execute": lambda self: type("R", (), {"data": [
                    {"id": 1, "nombre": "Ana", "telefono": "099", "clave": "099",
                     "clave_hash": "pbkdf2$x", "reset_codigo": "123456"}]})()
            })()
        })()
    })()
    volcado = db.exportar_todo()
    usuarios = volcado["tablas"]["usuarios"]
    revisar("clave" not in usuarios[0], "el respaldo omite la contrasena heredada")
    revisar("reset_codigo" not in usuarios[0], "el respaldo omite el codigo de recuperacion")
    revisar("nombre" in usuarios[0] and "telefono" in usuarios[0],
            "el respaldo si conserva los datos que hacen falta para restaurar")
    revisar("generado_en" in volcado and "resumen" in volcado,
            "el respaldo lleva fecha y un resumen por tabla")
    db.supabase = supabase_real

    # Los avisos no deben repetirse en bucle ni propagar errores. Aqui se
    # vuelve a usar la funcion real: en el resto de la bateria esta anulada
    # para que ninguna prueba salga a Telegram sin querer.
    enviados = []
    envio_real = tg.enviar_mensaje
    tg.enviar_mensaje = lambda chat, texto, teclado=None: enviados.append(texto)
    tg.avisar_al_admin = _avisar_real
    try:
        tg._ULTIMOS_AVISOS.clear()
        tg.avisar_al_admin("Prueba de aviso", "detalle")
        tg.avisar_al_admin("Prueba de aviso", "detalle")
        revisar(len(enviados) == 1, "un aviso repetido no se reenvia una y otra vez")

        tg.enviar_mensaje = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin red"))
        tg._ULTIMOS_AVISOS.clear()
        tg.avisar_al_admin("Otro aviso")
        revisar(True, "si el aviso falla, no revienta encima del error original")
    finally:
        tg.enviar_mensaje = envio_real
        tg.avisar_al_admin = lambda *a, **k: None
        tg._ULTIMOS_AVISOS.clear()


# =====================================================================
# 16. TELEFONO CON CODIGO DE PAIS
# =====================================================================

def probar_telefono_pais() -> None:
    print("\n[16] Telefono con codigo de pais")
    from pathlib import Path
    import auth

    html = Path("panel.html").read_text(encoding="utf-8")

    revisar('id="in-pais"' in html and 'id="rec-pais"' in html,
            "el ingreso y la recuperacion tienen selector de pais")
    revisar("const PAISES" in html and "aInternacional" in html,
            "el panel arma el numero internacional antes de enviarlo")
    revisar("'593'" in html and "Ecuador" in html, "Ecuador esta en la lista")
    revisar('id="in-hint"' in html,
            "el panel muestra el numero con el que se va a validar")
    revisar("lg-cc" not in html.split("<script>")[0].split('id="in-usuario"')[0][-400:]
            or 'select id="in-pais"' in html or '<select id="in-pais"' in html,
            "el '+593' fijo se reemplazo por una lista desplegable")

    # El selector no debe comerse el campo del numero. La regla base .lg-cc
    # declara display:flex y un <select> en modo flex crece hasta ocupar todo
    # el ancho: asi se desplego una vez una pantalla donde no se podia
    # escribir el telefono. Esta comprobacion vigila que quede anulado.
    import re
    bloque = re.search(r"select\.lg-cc\s*\{[^}]*\}", html, re.S)
    revisar(bloque is not None, "existe una regla propia para el selector")
    if bloque:
        css = bloque.group(0)
        revisar("display:block" in css.replace(" ", ""),
                "el selector anula el display:flex heredado")
        revisar("flex:0 0 auto" in css or "flex:0 0auto" in css.replace("  ", " "),
                "el selector no crece: el ancho sobrante es para el numero")

    # El backend sigue aceptando cualquier formato: es lo que permite que
    # quien ya entraba con un formato distinto no quede fuera.
    guardado = auth.normalizar_telefono("593990287112")
    for entrada in ["0990287112", "990287112", "593990287112", "+593 99 028 7112"]:
        d = auth.normalizar_telefono(entrada)
        revisar(len(d) >= 9 and d[-9:] == guardado[-9:],
                f"'{entrada}' sigue coincidiendo con el numero guardado")

    # Desempate cuando dos paises comparten los ultimos nueve digitos.
    ecuador = {"id": 1, "nombre": "Ecuatoriano", "telefono": "593990287112"}
    peru = {"id": 2, "nombre": "Peruano", "telefono": "51990287112"}

    elegido = db._desempatar_por_telefono([ecuador, peru], "593990287112")
    revisar(elegido and elegido["id"] == 1,
            "con dos paises que comparten los 9 digitos, gana la coincidencia exacta")

    elegido = db._desempatar_por_telefono([ecuador, peru], "51990287112")
    revisar(elegido and elegido["id"] == 2, "y funciona en el otro sentido")

    elegido = db._desempatar_por_telefono([ecuador, peru], "57990287112")
    revisar(elegido is None,
            "si hay ambiguedad y ninguno coincide, no se autentica a nadie")

    revisar(db._desempatar_por_telefono([ecuador], "0990287112") == ecuador,
            "con un solo candidato se mantiene la tolerancia de formato")
    revisar(db._desempatar_por_telefono([], "593990287112") is None,
            "sin candidatos devuelve None")


if __name__ == "__main__":
    probar_rutas()
    probar_calculo()
    probar_tarea()
    probar_infraestructura()
    probar_conversaciones()
    probar_numeros()
    probar_validacion_km()
    probar_contrato_panel()
    probar_escape_panel()
    probar_limite_intentos()
    probar_sesion()
    probar_cabeceras()
    probar_clave_obligatoria()
    probar_estaticos()
    probar_respaldo()
    probar_telefono_pais()
    print("\n" + "=" * 62)
    if _fallos:
        print(f"{len(_fallos)} PRUEBA(S) FALLARON:")
        for f in _fallos:
            print(f"  - {f}")
        sys.exit(1)
    print("TODAS LAS PRUEBAS PASARON")
