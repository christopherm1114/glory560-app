"""
web.py
------
La aplicación web (login + viñetas), servida desde el mismo servicio.

Estructura:
  Pantallas (HTML)
    GET  /panel                 -> la página (login o dashboard, según sesión)

  Sesión
    POST /api/login             -> iniciar sesión (teléfono/contraseña)
    POST /api/logout            -> cerrar sesión
    GET  /api/sesion            -> ¿quién soy? (rol y nombre) o 401

  Datos del propio usuario
    GET  /api/mis-datos         -> perfil, mantenimientos, insumos, gastos, km
    POST /api/perfil            -> modificar datos de mi vehículo

  Solo administrador
    GET  /api/aprobaciones      -> solicitudes pendientes
    POST /api/aprobar           -> aprobar una solicitud
    POST /api/rechazar          -> rechazar una solicitud
    GET  /api/usuarios          -> listado de usuarios con su vehículo
    GET  /api/usuario/{id}      -> detalle (resumen) de un usuario
    GET  /api/roles/buscar      -> buscar usuarios por nombre/teléfono
    POST /api/roles/cambiar     -> cambiar el rol de un usuario
"""

import os

from fastapi import APIRouter, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse

from datetime import datetime, timezone, timedelta

import hmac

import db
import auth
import mantenimiento
import telegram as tg

router = APIRouter()

# Cargamos la página HTML una sola vez.
_RUTA_HTML = os.path.join(os.path.dirname(__file__), "panel.html")
with open(_RUTA_HTML, encoding="utf-8") as f:
    _PANEL_HTML = f.read()


# ---------- Ayudas ----------

def _ip_cliente(request: Request) -> str:
    """
    Identifica al cliente para contar sus intentos fallidos.

    En Render la petición llega a través de Cloudflare, que escribe la IP real
    en 'cf-connecting-ip'. Esa es la fiable. 'x-forwarded-for' la puede
    falsificar quien llama, así que se usa solo como respaldo y sabiendo que
    un atacante decidido puede rotarla: por eso el límite por cuenta, que no
    depende de la IP, es la mitad importante de esta defensa.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def _demasiados_intentos(*claves: str):
    """
    Devuelve una respuesta 429 si alguna de las claves agotó sus intentos,
    o None si se puede continuar.
    """
    for clave in claves:
        if not auth.intento_permitido(clave):
            espera = auth.segundos_para_reintentar(clave)
            return JSONResponse(
                {"error": "demasiados_intentos", "reintentar_en": espera},
                status_code=429)
    return None


def _usuario_actual(request: Request, exigir_clave_propia: bool = True) -> dict | None:
    """
    Devuelve el usuario de la sesión (según la cookie) o None.

    Con exigir_clave_propia (lo normal), una cuenta que todavía entra con la
    credencial heredada —el teléfono— se trata como no autenticada: su sesión
    solo vale para /api/sesion y /api/cambiar-clave, que pasan False. Así el
    cambio de contraseña es obligatorio en la práctica, sin dejar fuera a los
    usuarios que ya existían.
    """
    leido = auth.leer_cookie_sesion(request.cookies.get("sesion"))
    if not leido:
        return None
    uid, marca = leido
    u = db.obtener_usuario(uid)
    if not u or u.get("estado") != "aprobado":
        return None
    # Si la contraseña cambió después de emitirse la cookie, la marca ya no
    # coincide y la sesión queda invalidada. Así, cambiar la contraseña
    # expulsa de verdad a quien estuviera dentro.
    if marca != auth.marca_credencial(u.get("clave_hash")):
        return None
    if exigir_clave_propia and auth.debe_cambiar_clave(u):
        return None
    return u


def _resumen_vehiculo(usuario: dict) -> dict:
    """Arma el bloque de datos del vehículo + insumos + mantenimientos de un usuario."""
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    if not vehiculo:
        return {"vehiculo": None}
    # Si la variante no se encuentra (id huérfano tras editar el catálogo a
    # mano), el panel debe seguir cargando: sin este respaldo, /api/mis-datos
    # devolvía un 500 y el usuario veía la página en blanco.
    variante = db.obtener_variante(vehiculo["variante_id"]) or {}
    tipos_full = {t["id"]: t for t in db.listar_tipos_mantenimiento()}
    tipos = {i: t["nombre"] for i, t in tipos_full.items()}

    # Separamos: los de 'reemplazo' van al semáforo (con precios); los de
    # 'inspeccion' van a Recomendaciones (tips de revisión, sin precio).
    promedios = db.promedios_por_tipo()
    proximos = []
    recomendaciones = []
    total_vencidos = 0.0
    for r in mantenimiento.calcular_estado_vehiculo(vehiculo):
        t = tipos_full.get(r["tipo_id"], {})
        if r.get("clase") == "inspeccion":
            recomendaciones.append({
                "nombre": r["nombre"], "categoria": r.get("categoria", "Otros"),
                "intervalo_km": r.get("intervalo_km"), "intervalo_meses": r.get("intervalo_meses"),
                "descripcion": t.get("descripcion"),
            })
            continue
        p = promedios.get(r["tipo_id"])
        prom = p["promedio"] if p else None
        proximos.append({
            "nombre": r["nombre"], "estado": r["estado"], "km_restante": r["km_restante"],
            "categoria": r.get("categoria", "Otros"), "clase": "reemplazo",
            "precio_promedio": prom, "conteo": p["conteo"] if p else 0,
            "mercado_min": t.get("mercado_min"), "mercado_max": t.get("mercado_max"),
            "mercado_nota": t.get("mercado_nota"),
        })
        if r["estado"] == "vencido" and prom:
            total_vencidos += prom
    hist = [
        {"nombre": tipos.get(r["tipo_mantenimiento_id"], "-"),
         "fecha": r["fecha"], "creado_en": r.get("creado_en"),
         "km": r["kilometraje"], "costo": r.get("costo"), "taller": r.get("taller")}
        for r in db.historial(vehiculo["id"], 50)
    ]
    gastos = db.gastos_por_categoria(vehiculo["id"])
    total = round(sum(float(g["total"]) for g in gastos), 2)

    return {
        "vehiculo": {
            "placa": vehiculo["placa"], "anio": vehiculo.get("anio_modelo"),
            "kilometraje": vehiculo.get("kilometraje_actual", 0),
            "id": vehiculo["id"], "variante_id": vehiculo["variante_id"],
        },
        "variante": {
            "nombre": variante.get("nombre", "-"),
            "motor": variante.get("motor", "-"),
            "transmision": variante.get("transmision", "-"),
            "aceite": f"{variante.get('aceite_motor','-')} · {variante.get('capacidad_aceite_l','-')} L",
            "bujia": variante.get("bujia_tipo", "-"),
            "frenos": f"{variante.get('refrigerante_l','')}",
            "transmision_liquido": (f"{variante.get('liquido_transmision','-')} · "
                                    f"{variante.get('capacidad_transmision_l','-')} L"),
            "refrigerante": f"{variante.get('refrigerante_l','-')} L",
            "llantas": f"{variante.get('medida_llanta','-')} · {variante.get('presion_llantas','-')}",
        },
        "proximos": proximos,
        "recomendaciones": recomendaciones,
        "total_vencidos_estimado": round(total_vencidos, 2),
        "ultimos": hist[:5],
        "historial": hist,
        "gastos_por_categoria": gastos,
        "total_gastos": total,
        "kilometraje_historial": db.historial_km(vehiculo["id"]),
    }


def _solo_admin(request: Request):
    u = _usuario_actual(request)
    if not u:
        return None, JSONResponse({"error": "no_autenticado"}, status_code=401)
    if u.get("rol") != "admin":
        return None, JSONResponse({"error": "no_autorizado"}, status_code=403)
    return u, None


# ---------- Página ----------

@router.get("/panel", response_class=HTMLResponse)
def panel():
    return HTMLResponse(_PANEL_HTML)


# ---------- Sesión ----------

@router.post("/api/login")
def api_login(request: Request, datos: dict = Body(...)):
    # Se frena ANTES de consultar la base de datos: validar_login descarga la
    # tabla de usuarios entera, así que cada intento sin freno era además una
    # forma barata de tumbar el servicio.
    usuario_pedido = auth.normalizar_telefono(datos.get("usuario", ""))
    clave_ip = f"login:ip:{_ip_cliente(request)}"
    clave_cuenta = f"login:cuenta:{usuario_pedido}"
    frenado = _demasiados_intentos(clave_ip, clave_cuenta)
    if frenado:
        return frenado

    persona = auth.validar_login(datos.get("usuario", ""), datos.get("contrasena", ""))
    if not persona:
        auth.registrar_fallo(clave_ip)
        auth.registrar_fallo(clave_cuenta)
        return JSONResponse({"error": "credenciales_invalidas"}, status_code=401)
    auth.limpiar_intentos(clave_ip)
    auth.limpiar_intentos(clave_cuenta)
    cookie = auth.crear_cookie_sesion(persona["id"], persona.get("clave_hash"))
    resp = JSONResponse({"ok": True, "rol": persona.get("rol", "usuario"),
                         "nombre": persona["nombre"],
                         "debe_cambiar": auth.debe_cambiar_clave(persona)})
    resp.set_cookie("sesion", cookie, httponly=True, secure=True, samesite="lax",
                    max_age=auth.MINUTOS_SESION * 60)
    return resp


@router.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sesion")
    return resp


# ---------- Contraseña: cambiar (estando dentro) ----------

@router.post("/api/cambiar-clave")
def api_cambiar_clave(request: Request, datos: dict = Body(...)):
    # exigir_clave_propia=False: esta es justamente la ruta que el usuario
    # necesita para salir del estado heredado.
    u = _usuario_actual(request, exigir_clave_propia=False)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    actual = datos.get("actual", "")
    nueva = datos.get("nueva", "")
    repetir = datos.get("repetir", "")
    if not auth.verificar_credencial(u, actual):
        return JSONResponse({"error": "actual_incorrecta"}, status_code=400)
    if nueva != repetir:
        return JSONResponse({"error": "no_coinciden"}, status_code=400)
    if not auth.contrasena_valida(nueva):
        return JSONResponse({"error": "debil"}, status_code=400)
    nuevo_hash = auth.hash_password(nueva)
    db.actualizar_clave_hash(u["id"], nuevo_hash)
    # El cambio invalida todas las sesiones, incluida la de quien lo hace: se
    # le entrega una cookie nueva para que no se quede fuera de su propia
    # pantalla, mientras cualquier otra sesion abierta muere aqui.
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sesion", auth.crear_cookie_sesion(u["id"], nuevo_hash),
                    httponly=True, secure=True, samesite="lax",
                    max_age=auth.MINUTOS_SESION * 60)
    return resp


# ---------- Contraseña: recuperación por Telegram ----------

@router.post("/api/recuperar/solicitar")
def api_recuperar_solicitar(request: Request, datos: dict = Body(...)):
    """Envía un código de 6 dígitos por Telegram. Siempre responde 'ok'
    (no revelamos si el teléfono existe o no)."""
    tel = auth.normalizar_telefono(datos.get("telefono", ""))
    # Sin freno, esta ruta es un cañón de mensajes de Telegram contra el
    # teléfono de cualquier usuario registrado.
    frenado = _demasiados_intentos(f"reset:pedir:{_ip_cliente(request)}",
                                   f"reset:pedir:{tel}")
    if frenado:
        return frenado
    auth.registrar_fallo(f"reset:pedir:{_ip_cliente(request)}")
    auth.registrar_fallo(f"reset:pedir:{tel}")
    persona = db.buscar_usuario_por_telefono_normalizado(tel)
    if persona and persona.get("estado") == "aprobado" and persona.get("telegram_id"):
        codigo = auth.generar_codigo()
        expira = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db.guardar_reset(persona["id"], codigo, expira)
        try:
            tg.enviar_mensaje(
                persona["telegram_id"],
                "🔐 <b>Recuperación de contraseña</b>\n"
                f"Tu código es <b>{codigo}</b>.\n"
                "Vence en 10 minutos. Si no lo solicitaste, ignora este mensaje.")
        except Exception as e:
            print(f"[recuperar] no se pudo enviar el código: {e}")
    return {"ok": True}


@router.post("/api/recuperar/confirmar")
def api_recuperar_confirmar(request: Request, datos: dict = Body(...)):
    tel = auth.normalizar_telefono(datos.get("telefono", ""))
    codigo = str(datos.get("codigo", "")).strip()
    nueva = datos.get("nueva", "")
    repetir = datos.get("repetir", "")

    # El código es de seis dígitos: sin límite de intentos se agota por fuerza
    # bruta. Con cinco intentos por ventana, adivinarlo deja de ser viable.
    clave_ip = f"reset:probar:{_ip_cliente(request)}"
    clave_cuenta = f"reset:probar:{tel}"
    frenado = _demasiados_intentos(clave_ip, clave_cuenta)
    if frenado:
        return frenado

    persona = db.buscar_usuario_por_telefono_normalizado(tel)
    if not persona:
        auth.registrar_fallo(clave_ip)
        auth.registrar_fallo(clave_cuenta)
        return JSONResponse({"error": "codigo_invalido"}, status_code=400)
    guardado = persona.get("reset_codigo") or ""
    # Comparación en tiempo constante: con != el tiempo de respuesta filtra
    # cuántos dígitos iniciales se acertaron (Hallazgo 10).
    if not guardado or not hmac.compare_digest(str(guardado), codigo):
        auth.registrar_fallo(clave_ip)
        auth.registrar_fallo(clave_cuenta)
        # Tras agotar los intentos, el código deja de servir aunque siga
        # vigente: si no, el atacante espera a que pase la ventana y sigue.
        if not auth.intento_permitido(clave_cuenta):
            db.limpiar_reset(persona["id"])
        return JSONResponse({"error": "codigo_invalido"}, status_code=400)
    # ¿Vigente?
    try:
        if datetime.fromisoformat(persona["reset_expira"]) < datetime.now(timezone.utc):
            return JSONResponse({"error": "codigo_expirado"}, status_code=400)
    except (ValueError, TypeError):
        return JSONResponse({"error": "codigo_invalido"}, status_code=400)
    if nueva != repetir:
        return JSONResponse({"error": "no_coinciden"}, status_code=400)
    if not auth.contrasena_valida(nueva):
        return JSONResponse({"error": "debil"}, status_code=400)

    db.actualizar_clave_hash(persona["id"], auth.hash_password(nueva))
    db.limpiar_reset(persona["id"])
    auth.limpiar_intentos(clave_ip)
    auth.limpiar_intentos(clave_cuenta)
    return {"ok": True}


@router.get("/api/sesion")
def api_sesion(request: Request):
    # Tambien con False: el panel necesita saber quien es para poder mostrarle
    # la pantalla de cambio obligatorio.
    u = _usuario_actual(request, exigir_clave_propia=False)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    # Renovamos la cookie (sesión "deslizante"): mientras el usuario esté
    # activo, la app llama a esta ruta y la sesión se mantiene viva.
    resp = JSONResponse({"nombre": u["nombre"], "rol": u.get("rol", "usuario"),
                         "telefono": u["telefono"],
                         "debe_cambiar": auth.debe_cambiar_clave(u)})
    # La cookie renovada debe llevar la marca de la credencial VIGENTE; si se
    # emitiera sin ella, la comprobacion de _usuario_actual fallaria en la
    # siguiente peticion y el usuario quedaria fuera cada pocos segundos.
    resp.set_cookie("sesion", auth.crear_cookie_sesion(u["id"], u.get("clave_hash")),
                    httponly=True, secure=True,
                    samesite="lax", max_age=auth.MINUTOS_SESION * 60)
    return resp


# ---------- Datos del propio usuario ----------

@router.get("/api/mis-datos")
def api_mis_datos(request: Request):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    datos = _resumen_vehiculo(u)
    datos["usuario"] = {"nombre": u["nombre"], "telefono": u["telefono"], "rol": u.get("rol")}
    return datos


@router.post("/api/perfil")
def api_perfil(request: Request, cambios: dict = Body(...)):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    vehiculo = db.buscar_vehiculo_de_usuario(u["id"])
    if not vehiculo:
        return JSONResponse({"error": "sin_vehiculo"}, status_code=404)

    actualizar = {}
    if "placa" in cambios and cambios["placa"]:
        actualizar["placa"] = str(cambios["placa"]).upper()
    if "anio" in cambios and str(cambios["anio"]).isdigit():
        actualizar["anio_modelo"] = int(cambios["anio"])
    if "kilometraje" in cambios and str(cambios["kilometraje"]).isdigit():
        km = int(cambios["kilometraje"])
        # El perfil es la vía de CORRECCIÓN: aquí sí se puede bajar el odómetro
        # para arreglar un dato mal tecleado. Solo se filtra lo imposible.
        if km <= 0 or km > mantenimiento.KM_MAXIMO_RAZONABLE:
            return JSONResponse({"error": "km_invalido"}, status_code=400)
        actualizar["kilometraje_actual"] = km
        actualizar["fecha_actualizacion_km"] = db._hoy()
        db.registrar_lectura_km(vehiculo["id"], km)
    # Cambio de variante (motor + transmisión)
    if cambios.get("motor") and cambios.get("transmision"):
        variante = db.buscar_variante(cambios["motor"], cambios["transmision"])
        if variante:
            actualizar["variante_id"] = variante["id"]

    if actualizar:
        db.actualizar_vehiculo(vehiculo["id"], actualizar)
    return {"ok": True}


# ---------- Mantenimientos registrados (listar / crear / eliminar) ----------

import re as _re

@router.get("/api/tipos")
def api_tipos(request: Request):
    if not _usuario_actual(request):
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    return {"tipos": [{"id": t["id"], "nombre": t["nombre"]} for t in db.listar_tipos_mantenimiento()]}


@router.get("/api/mantenimientos")
def api_mantenimientos(request: Request):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    vehiculo = db.buscar_vehiculo_de_usuario(u["id"])
    if not vehiculo:
        return {"mantenimientos": []}
    tipos = {t["id"]: t["nombre"] for t in db.listar_tipos_mantenimiento()}
    lista = [{
        "id": r["id"], "tipo_id": r["tipo_mantenimiento_id"],
        "nombre": tipos.get(r["tipo_mantenimiento_id"], "-"),
        "fecha": r["fecha"], "creado_en": r.get("creado_en"),
        "km": r["kilometraje"], "costo": r.get("costo"), "taller": r.get("taller"),
    } for r in db.historial(vehiculo["id"], 200)]
    return {"mantenimientos": lista}


@router.post("/api/mantenimiento/crear")
def api_mant_crear(request: Request, datos: dict = Body(...)):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    vehiculo = db.buscar_vehiculo_de_usuario(u["id"])
    if not vehiculo:
        return JSONResponse({"error": "sin_vehiculo"}, status_code=404)
    try:
        tipo_id = int(datos.get("tipo_id"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "tipo_invalido"}, status_code=400)
    try:
        km = int(datos.get("km"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "km_invalido"}, status_code=400)
    # Misma regla que en el bot: un servicio registrado a más kilómetros que el
    # odómetro se vuelve línea base del cálculo y deja ese control en verde
    # para siempre. El panel no puede ser una puerta trasera a ese estado.
    aceptado, motivo = mantenimiento.validar_km_servicio(km, vehiculo.get("kilometraje_actual"))
    if not aceptado:
        return JSONResponse({"error": "km_invalido", "detalle": motivo}, status_code=400)
    try:
        costo = float(datos.get("costo"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "costo_invalido"}, status_code=400)
    if costo <= 0 or costo > 5000:
        return JSONResponse({"error": "costo_invalido"}, status_code=400)
    fecha = datos.get("fecha") or ""
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
        fecha = db._hoy()
    taller = (datos.get("taller") or "").strip() or None

    db.crear_mantenimiento(vehiculo["id"], tipo_id, fecha, km, round(costo, 2), taller, None)
    if km > (vehiculo.get("kilometraje_actual") or 0):
        db.actualizar_vehiculo(vehiculo["id"], {"kilometraje_actual": km, "fecha_actualizacion_km": db._hoy()})
        db.registrar_lectura_km(vehiculo["id"], km)
    return {"ok": True}


@router.post("/api/mantenimiento/eliminar")
def api_mant_eliminar(request: Request, datos: dict = Body(...)):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    vehiculo = db.buscar_vehiculo_de_usuario(u["id"])
    if not vehiculo:
        return JSONResponse({"error": "sin_vehiculo"}, status_code=404)
    try:
        m = db.obtener_mantenimiento(int(datos.get("id")))
    except (TypeError, ValueError):
        return JSONResponse({"error": "id_invalido"}, status_code=400)
    # Solo puede borrar mantenimientos de SU propio vehículo.
    if not m or m["vehiculo_id"] != vehiculo["id"]:
        return JSONResponse({"error": "no_encontrado"}, status_code=404)
    db.eliminar_mantenimiento(m["id"])
    return {"ok": True}


# ---------- Administrador ----------

@router.get("/api/aprobaciones")
def api_aprobaciones(request: Request):
    u, err = _solo_admin(request)
    if err:
        return err
    pendientes = []
    for p in db.listar_usuarios_pendientes():
        veh = db.buscar_vehiculo_de_usuario(p["id"])
        placa = veh["placa"] if veh else "-"
        pendientes.append({"id": p["id"], "nombre": p["nombre"], "telefono": p["telefono"], "placa": placa})
    return {"pendientes": pendientes}


@router.post("/api/aprobar")
def api_aprobar(request: Request, datos: dict = Body(...)):
    u, err = _solo_admin(request)
    if err:
        return err
    db.actualizar_usuario(int(datos["id"]), {"estado": "aprobado"})
    return {"ok": True}


@router.post("/api/rechazar")
def api_rechazar(request: Request, datos: dict = Body(...)):
    u, err = _solo_admin(request)
    if err:
        return err
    db.actualizar_usuario(int(datos["id"]), {"estado": "rechazado"})
    return {"ok": True}


@router.get("/api/usuarios")
def api_usuarios(request: Request):
    u, err = _solo_admin(request)
    if err:
        return err
    lista = []
    for p in db.listar_usuarios_aprobados():
        veh = db.buscar_vehiculo_de_usuario(p["id"])
        variante = db.obtener_variante(veh["variante_id"]) if veh else None
        lista.append({
            "id": p["id"], "nombre": p["nombre"], "telefono": p["telefono"], "rol": p.get("rol"),
            "placa": veh["placa"] if veh else "-",
            "variante": variante["nombre"] if variante else "-",
        })
    return {"usuarios": lista}


@router.get("/api/usuario/{usuario_id}")
def api_usuario_detalle(request: Request, usuario_id: int):
    u, err = _solo_admin(request)
    if err:
        return err
    persona = db.obtener_usuario(usuario_id)
    if not persona:
        return JSONResponse({"error": "no_existe"}, status_code=404)
    datos = _resumen_vehiculo(persona)
    datos["usuario"] = {"nombre": persona["nombre"], "telefono": persona["telefono"], "rol": persona.get("rol")}
    return datos


@router.get("/api/roles/buscar")
def api_roles_buscar(request: Request, q: str = ""):
    u, err = _solo_admin(request)
    if err:
        return err
    resultados = [
        {"id": p["id"], "nombre": p["nombre"], "telefono": p["telefono"], "rol": p.get("rol", "usuario")}
        for p in db.buscar_usuarios(q) if q.strip()
    ]
    return {"resultados": resultados}


@router.post("/api/roles/cambiar")
def api_roles_cambiar(request: Request, datos: dict = Body(...)):
    u, err = _solo_admin(request)
    if err:
        return err
    nuevo = "admin" if datos.get("rol") == "admin" else "usuario"
    # Evita que el admin se quite el rol a sí mismo por error.
    if int(datos["id"]) == u["id"] and nuevo != "admin":
        return JSONResponse({"error": "no_puedes_quitarte_admin"}, status_code=400)
    db.actualizar_usuario(int(datos["id"]), {"rol": nuevo})
    return {"ok": True}
