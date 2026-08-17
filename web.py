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

def _usuario_actual(request: Request) -> dict | None:
    """Devuelve el usuario de la sesión (según la cookie) o None."""
    uid = auth.leer_cookie_sesion(request.cookies.get("sesion"))
    if not uid:
        return None
    u = db.obtener_usuario(uid)
    if not u or u.get("estado") != "aprobado":
        return None
    return u


def _resumen_vehiculo(usuario: dict) -> dict:
    """Arma el bloque de datos del vehículo + insumos + mantenimientos de un usuario."""
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    if not vehiculo:
        return {"vehiculo": None}
    variante = db.obtener_variante(vehiculo["variante_id"])
    tipos_full = {t["id"]: t for t in db.listar_tipos_mantenimiento()}
    tipos = {i: t["nombre"] for i, t in tipos_full.items()}

    # Próximos mantenimientos con el precio promedio de la comunidad
    # y el precio de mercado referencial.
    promedios = db.promedios_por_tipo()
    proximos = []
    total_vencidos = 0.0
    for r in mantenimiento.calcular_estado_vehiculo(vehiculo):
        p = promedios.get(r["tipo_id"])
        prom = p["promedio"] if p else None
        t = tipos_full.get(r["tipo_id"], {})
        proximos.append({
            "nombre": r["nombre"], "estado": r["estado"], "km_restante": r["km_restante"],
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
            "nombre": variante["nombre"], "motor": variante["motor"], "transmision": variante["transmision"],
            "aceite": f"{variante['aceite_motor']} · {variante['capacidad_aceite_l']} L",
            "bujia": variante["bujia_tipo"],
            "frenos": f"{variante.get('refrigerante_l','')}",
            "transmision_liquido": f"{variante['liquido_transmision']} · {variante['capacidad_transmision_l']} L",
            "refrigerante": f"{variante['refrigerante_l']} L",
            "llantas": f"{variante['medida_llanta']} · {variante['presion_llantas']}",
        },
        "proximos": proximos,
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
def api_login(datos: dict = Body(...)):
    persona = auth.validar_login(datos.get("usuario", ""), datos.get("contrasena", ""))
    if not persona:
        return JSONResponse({"error": "credenciales_invalidas"}, status_code=401)
    cookie = auth.crear_cookie_sesion(persona["id"])
    resp = JSONResponse({"ok": True, "rol": persona.get("rol", "usuario"), "nombre": persona["nombre"]})
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
    u = _usuario_actual(request)
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
    db.actualizar_clave_hash(u["id"], auth.hash_password(nueva))
    return {"ok": True}


# ---------- Contraseña: recuperación por Telegram ----------

@router.post("/api/recuperar/solicitar")
def api_recuperar_solicitar(datos: dict = Body(...)):
    """Envía un código de 6 dígitos por Telegram. Siempre responde 'ok'
    (no revelamos si el teléfono existe o no)."""
    tel = auth.normalizar_telefono(datos.get("telefono", ""))
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
def api_recuperar_confirmar(datos: dict = Body(...)):
    tel = auth.normalizar_telefono(datos.get("telefono", ""))
    codigo = str(datos.get("codigo", "")).strip()
    nueva = datos.get("nueva", "")
    repetir = datos.get("repetir", "")

    persona = db.buscar_usuario_por_telefono_normalizado(tel)
    if not persona:
        return JSONResponse({"error": "codigo_invalido"}, status_code=400)
    if not persona.get("reset_codigo") or persona["reset_codigo"] != codigo:
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
    return {"ok": True}


@router.get("/api/sesion")
def api_sesion(request: Request):
    u = _usuario_actual(request)
    if not u:
        return JSONResponse({"error": "no_autenticado"}, status_code=401)
    # Renovamos la cookie (sesión "deslizante"): mientras el usuario esté
    # activo, la app llama a esta ruta y la sesión se mantiene viva.
    resp = JSONResponse({"nombre": u["nombre"], "rol": u.get("rol", "usuario"), "telefono": u["telefono"]})
    resp.set_cookie("sesion", auth.crear_cookie_sesion(u["id"]), httponly=True, secure=True,
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
