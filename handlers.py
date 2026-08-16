"""
handlers.py
-----------
El "cerebro" del bot: decide qué hacer con cada mensaje que llega.

Telegram nos envía "updates" (actualizaciones). Los dos tipos que usamos son:
  - message: el usuario escribió texto o compartió su contacto.
  - callback_query: el usuario tocó un botón inline.

El registro tiene varias preguntas, así que usamos una "máquina de estados":
recordamos en qué PASO va cada usuario (en la tabla estado_conversacion) y,
según el paso, interpretamos su respuesta.
"""

import db
import telegram as tg
import mantenimiento
from config import ADMIN_TELEGRAM_ID


# =====================================================================
# PUNTO DE ENTRADA: recibe cada update y decide a dónde mandarlo.
# =====================================================================

def procesar_update(update: dict) -> None:
    try:
        if "message" in update:
            _manejar_mensaje(update["message"])
        elif "callback_query" in update:
            _manejar_callback(update["callback_query"])
    except Exception as e:
        # Nunca dejamos que un error tumbe el webhook; lo registramos en el log.
        print(f"[ERROR] procesando update: {e}")


# =====================================================================
# MENSAJES DE TEXTO Y CONTACTOS
# =====================================================================

def _manejar_mensaje(mensaje: dict) -> None:
    chat_id = mensaje["chat"]["id"]
    telegram_id = mensaje["from"]["id"]
    texto = (mensaje.get("text") or "").strip()
    contacto = mensaje.get("contact")

    usuario = db.buscar_usuario_por_telegram(telegram_id)
    estado = db.obtener_estado(telegram_id)

    # --- Comandos (empiezan con "/") ---
    if texto.startswith("/"):
        _manejar_comando(chat_id, telegram_id, texto, usuario)
        return

    # --- Si el usuario compartió su contacto durante el registro ---
    if contacto and estado["paso"] == "reg_telefono":
        _reg_recibir_telefono(chat_id, telegram_id, contacto, estado)
        return

    # --- Si estamos a mitad de una conversación, seguimos el flujo ---
    if estado["paso"]:
        _continuar_conversacion(chat_id, telegram_id, texto, estado, usuario)
        return

    # --- Si no hay nada en curso, mostramos ayuda ---
    tg.enviar_mensaje(chat_id, "No entendí. Escribe /ayuda para ver qué puedo hacer.")


def _manejar_comando(chat_id, telegram_id, texto, usuario) -> None:
    # El comando puede venir con argumentos: "/km 45000" -> partes[0]="/km"
    partes = texto.split()
    comando = partes[0].lower()
    args = partes[1:]

    if comando == "/start":
        _comando_start(chat_id, telegram_id, usuario)
    elif comando == "/ayuda":
        _comando_ayuda(chat_id, usuario)
    elif comando == "/cancelar":
        db.limpiar_estado(telegram_id)
        tg.enviar_mensaje(chat_id, "Operación cancelada. Escribe /ayuda cuando quieras.")
    # --- A partir de aquí, hace falta estar aprobado ---
    elif comando == "/perfil":
        _comando_perfil(chat_id, telegram_id, usuario)
    elif comando == "/insumos":
        _comando_insumos(chat_id, usuario)
    elif comando == "/proximo":
        _comando_proximo(chat_id, usuario)
    elif comando == "/km":
        _comando_km(chat_id, telegram_id, usuario, args)
    elif comando == "/registrar":
        _comando_registrar(chat_id, telegram_id, usuario)
    elif comando == "/historial":
        _comando_historial(chat_id, usuario)
    # --- Comandos de administrador ---
    elif comando in ("/aprobar", "/rechazar"):
        _comando_admin(chat_id, telegram_id, comando, args)
    else:
        tg.enviar_mensaje(chat_id, "Comando no reconocido. Escribe /ayuda.")


# =====================================================================
# /start  y  REGISTRO (cuestionario paso a paso)
# =====================================================================

def _comando_start(chat_id, telegram_id, usuario) -> None:
    # Caso 1: ya está registrado y aprobado.
    if usuario and usuario["estado"] == "aprobado":
        tg.enviar_mensaje(chat_id,
            f"¡Hola de nuevo, {usuario['nombre']}! 👋\nEscribe /ayuda para ver las opciones.")
        return
    # Caso 2: registrado pero aún pendiente.
    if usuario and usuario["estado"] == "pendiente":
        tg.enviar_mensaje(chat_id,
            "Tu cuenta está <b>pendiente de aprobación</b>. Te avisaré cuando esté lista. 🙌")
        return
    # Caso 3: rechazado.
    if usuario and usuario["estado"] == "rechazado":
        tg.enviar_mensaje(chat_id, "Tu solicitud fue rechazada. Contacta al administrador.")
        return

    # Caso 4: usuario nuevo -> empezamos el registro.
    db.guardar_estado(telegram_id, "reg_telefono", {})
    tg.enviar_mensaje(chat_id,
        "¡Bienvenido a <b>Control de Mantenimientos Glory 560</b>! 🚗\n\n"
        "Voy a hacerte unas preguntas para registrar tu vehículo.\n"
        "Primero, toca el botón para compartir tu número de teléfono:",
        teclado=tg.boton_compartir_telefono())


def _reg_recibir_telefono(chat_id, telegram_id, contacto, estado) -> None:
    telefono = contacto.get("phone_number", "")
    # Verificamos que no exista ya otro usuario con ese teléfono.
    if db.buscar_usuario_por_telefono(telefono):
        db.limpiar_estado(telegram_id)
        tg.enviar_mensaje(chat_id,
            "Ese número ya está registrado. Escribe /start si necesitas ayuda.",
            teclado=tg.quitar_teclado())
        return
    datos = estado["datos"]
    datos["telefono"] = telefono
    db.guardar_estado(telegram_id, "reg_nombre", datos)
    tg.enviar_mensaje(chat_id, "¡Gracias! ✅\n\n<b>1.</b> ¿Cuál es tu nombre completo?",
                      teclado=tg.quitar_teclado())


def _continuar_conversacion(chat_id, telegram_id, texto, estado, usuario) -> None:
    """Interpreta el texto según el paso en el que va el usuario."""
    paso = estado["paso"]
    datos = estado["datos"]

    # ---------- Registro ----------
    if paso == "reg_nombre":
        datos["nombre"] = texto
        db.guardar_estado(telegram_id, "reg_placa", datos)
        tg.enviar_mensaje(chat_id, "<b>2.</b> ¿Cuál es la placa de tu Glory 560? (ej. PXX-1234)")

    elif paso == "reg_placa":
        datos["placa"] = texto.upper()
        db.guardar_estado(telegram_id, "reg_anio", datos)
        tg.enviar_mensaje(chat_id, "<b>3.</b> ¿De qué año es tu vehículo? (ej. 2023, 2027)")

    elif paso == "reg_anio":
        anio = _a_entero(texto)
        if anio is None or anio < 2015 or anio > 2035:
            tg.enviar_mensaje(chat_id, "Por favor escribe un año válido (ej. 2023).")
            return
        datos["anio"] = anio
        db.guardar_estado(telegram_id, "reg_motor", datos)
        tg.enviar_mensaje(chat_id,
            "<b>4.</b> ¿Qué motor tiene tu Glory 560?\n"
            "<i>Pista: el 1.5 Turbo suele llevar una 'T' atrás; el 1.8 es aspirado.</i>",
            teclado=tg.teclado_inline([[("1.8 Aspirado", "motor:1.8 Aspirado"),
                                        ("1.5 Turbo", "motor:1.5 Turbo")]]))

    elif paso == "reg_km":
        km = _a_entero(texto)
        if km is None or km < 0:
            tg.enviar_mensaje(chat_id, "Escribe el kilometraje como un número (ej. 45000).")
            return
        datos["kilometraje"] = km
        db.guardar_estado(telegram_id, "reg_fecha_aceite", datos)
        tg.enviar_mensaje(chat_id,
            "<b>7.</b> ¿Recuerdas la fecha del último cambio de aceite? "
            "Escríbela como AAAA-MM-DD (ej. 2026-05-20), o toca <b>Omitir</b>.",
            teclado=tg.teclado_inline([[("Omitir", "aceite:omitir")]]))

    elif paso == "reg_fecha_aceite":
        # El usuario escribió una fecha en lugar de tocar el botón.
        datos["fecha_ultimo_aceite"] = texto
        _finalizar_registro(chat_id, telegram_id, datos)

    # ---------- Modificar perfil ----------
    elif paso.startswith("perfil_edit:"):
        campo = paso.split(":", 1)[1]
        _aplicar_edicion_perfil(chat_id, telegram_id, usuario, campo, texto)

    # ---------- Registrar un mantenimiento ----------
    elif paso == "mant_km":
        km = _a_entero(texto)
        if km is None:
            tg.enviar_mensaje(chat_id, "Escribe el kilometraje como número (ej. 45000).")
            return
        datos["km"] = km
        db.guardar_estado(telegram_id, "mant_costo", datos)
        tg.enviar_mensaje(chat_id, "¿Cuánto costó? Escribe el valor en dólares, mayor a 0 (ej. 35).")

    elif paso == "mant_costo":
        costo = _a_numero(texto)
        # El costo debe ser positivo y coherente (hasta $5000). Así el precio
        # promedio de la comunidad no se distorsiona con ceros o errores de tipeo.
        if costo is None or costo <= 0 or costo > 5000:
            tg.enviar_mensaje(chat_id,
                "El costo debe ser un valor en dólares mayor a 0 y hasta 5000 (ej. 35). Inténtalo de nuevo:")
            return
        datos["costo"] = round(costo, 2)
        db.guardar_estado(telegram_id, "mant_taller", datos)
        tg.enviar_mensaje(chat_id, "¿En qué taller? (o escribe '-' para dejarlo vacío)")

    elif paso == "mant_taller":
        datos["taller"] = None if texto == "-" else texto
        _finalizar_registro_mantenimiento(chat_id, telegram_id, usuario, datos)

    else:
        # Paso desconocido: reiniciamos por seguridad.
        db.limpiar_estado(telegram_id)
        tg.enviar_mensaje(chat_id, "Reinicié la conversación. Escribe /ayuda.")


def _finalizar_registro(chat_id, telegram_id, datos) -> None:
    """Crea el usuario y el vehículo, y avisa al administrador."""
    variante = db.buscar_variante(datos["motor"], datos["transmision"])
    if not variante:
        db.limpiar_estado(telegram_id)
        tg.enviar_mensaje(chat_id, "No pude identificar la variante. Escribe /start para reintentar.")
        return

    usuario = db.crear_usuario(telegram_id, datos["telefono"], datos["nombre"])
    vehiculo = db.crear_vehiculo(
        usuario_id=usuario["id"],
        variante_id=variante["id"],
        placa=datos["placa"],
        anio=datos.get("anio"),
        kilometraje=datos.get("kilometraje", 0),
        fecha_ultimo_aceite=datos.get("fecha_ultimo_aceite"),
    )
    # Guardamos la primera lectura de kilometraje (para el gráfico del dashboard).
    db.registrar_lectura_km(vehiculo["id"], datos.get("kilometraje", 0))
    db.limpiar_estado(telegram_id)

    # Resumen para el usuario con los insumos de SU variante.
    tg.enviar_mensaje(chat_id,
        f"✅ <b>Registro recibido.</b>\n\n"
        f"Detecté tu Glory 560 <b>{datos.get('anio','')}</b>, variante <b>{variante['nombre']}</b> "
        f"({variante['motor']} / {variante['transmision']}).\n\n"
        f"Según el manual, tu vehículo usa:\n"
        f"• Aceite de motor: <b>{variante['aceite_motor']}</b> ({variante['capacidad_aceite_l']} L)\n"
        f"• Bujías: <b>{variante['bujia_tipo']}</b>\n"
        f"• Líquido de transmisión: <b>{variante['liquido_transmision']}</b>\n\n"
        f"Tu solicitud quedó <b>pendiente de aprobación</b>. Te avisaré cuando esté lista. 🙌")

    # Aviso al administrador.
    if ADMIN_TELEGRAM_ID:
        tg.enviar_mensaje(ADMIN_TELEGRAM_ID,
            f"🔔 <b>Nueva solicitud de registro</b>\n"
            f"ID usuario: <b>{usuario['id']}</b>\n"
            f"Nombre: {datos['nombre']}\n"
            f"Teléfono: {datos['telefono']}\n"
            f"Placa: {datos['placa']} · Año: {datos.get('anio','')}\n"
            f"Variante: {variante['nombre']}\n\n"
            f"Para aprobar: <code>/aprobar {usuario['id']}</code>\n"
            f"Para rechazar: <code>/rechazar {usuario['id']}</code>")


# =====================================================================
# BOTONES INLINE (callback_query)
# =====================================================================

def _manejar_callback(callback: dict) -> None:
    chat_id = callback["message"]["chat"]["id"]
    telegram_id = callback["from"]["id"]
    dato = callback.get("data", "")          # lo que pusimos en callback_data
    tg.responder_callback(callback["id"])    # quita el "relojito" del botón

    estado = db.obtener_estado(telegram_id)
    datos = estado["datos"]
    usuario = db.buscar_usuario_por_telegram(telegram_id)

    # --- Elección de motor durante el registro ---
    if dato.startswith("motor:") and estado["paso"] == "reg_motor":
        datos["motor"] = dato.split(":", 1)[1]
        db.guardar_estado(telegram_id, "reg_transmision", datos)
        tg.enviar_mensaje(chat_id, "<b>5.</b> ¿Qué transmisión tiene?",
            teclado=tg.teclado_inline([[("Manual", "trans:Manual"),
                                        ("Automática CVT", "trans:CVT")]]))

    # --- Elección de transmisión: aquí derivamos la variante ---
    elif dato.startswith("trans:") and estado["paso"] == "reg_transmision":
        eleccion = dato.split(":", 1)[1]
        # El código de caja depende del motor: 1.8->5MT, 1.5T->6MT, o CVT.
        if eleccion == "CVT":
            datos["transmision"] = "CVT"
        elif datos.get("motor") == "1.8 Aspirado":
            datos["transmision"] = "5MT"
        else:
            datos["transmision"] = "6MT"
        db.guardar_estado(telegram_id, "reg_km", datos)
        tg.enviar_mensaje(chat_id, "<b>6.</b> ¿Cuál es el kilometraje actual? (ej. 45000)")

    # --- Omitir la fecha del último aceite ---
    elif dato == "aceite:omitir" and estado["paso"] == "reg_fecha_aceite":
        datos["fecha_ultimo_aceite"] = None
        _finalizar_registro(chat_id, telegram_id, datos)

    # --- Menú de modificar perfil: el usuario eligió qué campo editar ---
    elif dato.startswith("editar:"):
        _pedir_nuevo_valor(chat_id, telegram_id, dato.split(":", 1)[1], datos)

    # --- Cambiar variante: eligió nuevo motor ---
    elif dato.startswith("nvmotor:"):
        datos["nuevo_motor"] = dato.split(":", 1)[1]
        db.guardar_estado(telegram_id, "perfil_variante_trans", datos)
        tg.enviar_mensaje(chat_id, "¿Y la transmisión?",
            teclado=tg.teclado_inline([[("Manual", "nvtrans:Manual"),
                                        ("Automática CVT", "nvtrans:CVT")]]))

    # --- Cambiar variante: eligió nueva transmisión -> confirma ---
    elif dato.startswith("nvtrans:"):
        eleccion = dato.split(":", 1)[1]
        motor = datos.get("nuevo_motor", "")
        if eleccion == "CVT":
            trans = "CVT"
        elif motor == "1.8 Aspirado":
            trans = "5MT"
        else:
            trans = "6MT"
        _aplicar_cambio_variante(chat_id, telegram_id, usuario, motor, trans)

    # --- Registrar mantenimiento: eligió el tipo de control ---
    elif dato.startswith("tipo:") and estado["paso"] == "mant_tipo":
        datos["tipo_id"] = int(dato.split(":", 1)[1])
        db.guardar_estado(telegram_id, "mant_km", datos)
        tg.enviar_mensaje(chat_id, "¿A qué kilometraje se hizo? (ej. 45000)")


# =====================================================================
# /perfil  y  MODIFICAR PERFIL
# =====================================================================

def _comando_perfil(chat_id, telegram_id, usuario) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    variante = db.obtener_variante(vehiculo["variante_id"]) if vehiculo else None

    texto = (f"👤 <b>Tu perfil</b>\n"
             f"Nombre: {usuario['nombre']}\n"
             f"Teléfono: {usuario['telefono']}\n\n")
    if vehiculo and variante:
        texto += (f"🚗 <b>Tu vehículo</b>\n"
                  f"Placa: {vehiculo['placa']}\n"
                  f"Año: {vehiculo.get('anio_modelo','-')}\n"
                  f"Variante: {variante['nombre']} ({variante['motor']} / {variante['transmision']})\n"
                  f"Kilometraje: {vehiculo.get('kilometraje_actual',0)} km")

    # Guardamos el id del vehículo en el estado para las ediciones.
    db.guardar_estado(telegram_id, "perfil_menu",
                      {"vehiculo_id": vehiculo["id"] if vehiculo else None})

    tg.enviar_mensaje(chat_id, texto, teclado=tg.teclado_inline([
        [("✏️ Nombre", "editar:nombre"), ("✏️ Placa", "editar:placa")],
        [("✏️ Año", "editar:anio"), ("✏️ Kilometraje", "editar:km")],
        [("🔧 Motor/Transmisión (variante)", "editar:variante")],
    ]))


def _pedir_nuevo_valor(chat_id, telegram_id, campo, datos) -> None:
    """El usuario tocó un botón del menú de perfil; le pedimos el nuevo valor."""
    if campo == "variante":
        # Cambiar la variante recalcula insumos e intervalos: avisamos.
        db.guardar_estado(telegram_id, "perfil_variante_motor", datos)
        tg.enviar_mensaje(chat_id,
            "⚠️ Cambiar el motor o la transmisión <b>recalcula</b> el aceite, la bujía, "
            "los líquidos y los intervalos.\n\n¿Qué motor tiene?",
            teclado=tg.teclado_inline([[("1.8 Aspirado", "nvmotor:1.8 Aspirado"),
                                        ("1.5 Turbo", "nvmotor:1.5 Turbo")]]))
        return

    preguntas = {
        "nombre": "Escribe el nuevo nombre:",
        "placa": "Escribe la nueva placa:",
        "anio": "Escribe el nuevo año (ej. 2023):",
        "km": "Escribe el kilometraje actual (ej. 46000):",
    }
    db.guardar_estado(telegram_id, f"perfil_edit:{campo}", datos)
    tg.enviar_mensaje(chat_id, preguntas.get(campo, "Escribe el nuevo valor:"))


def _aplicar_edicion_perfil(chat_id, telegram_id, usuario, campo, texto) -> None:
    estado = db.obtener_estado(telegram_id)
    vehiculo_id = estado["datos"].get("vehiculo_id")

    if campo == "nombre":
        db.actualizar_usuario(usuario["id"], {"nombre": texto})
    elif campo == "placa":
        db.actualizar_vehiculo(vehiculo_id, {"placa": texto.upper()})
    elif campo == "anio":
        anio = _a_entero(texto)
        if anio is None:
            tg.enviar_mensaje(chat_id, "Año inválido. Intenta de nuevo (ej. 2023).")
            return
        db.actualizar_vehiculo(vehiculo_id, {"anio_modelo": anio})
    elif campo == "km":
        km = _a_entero(texto)
        if km is None:
            tg.enviar_mensaje(chat_id, "Kilometraje inválido. Intenta de nuevo.")
            return
        db.actualizar_vehiculo(vehiculo_id, {"kilometraje_actual": km,
                                             "fecha_actualizacion_km": db._hoy()})
        db.registrar_lectura_km(vehiculo_id, km)

    db.limpiar_estado(telegram_id)
    tg.enviar_mensaje(chat_id, "✅ Dato actualizado. Escribe /perfil para verlo.")


def _aplicar_cambio_variante(chat_id, telegram_id, usuario, motor, trans) -> None:
    variante = db.buscar_variante(motor, trans)
    estado = db.obtener_estado(telegram_id)
    vehiculo_id = estado["datos"].get("vehiculo_id")
    if not variante or not vehiculo_id:
        db.limpiar_estado(telegram_id)
        tg.enviar_mensaje(chat_id, "No pude actualizar la variante. Escribe /perfil e intenta otra vez.")
        return
    db.actualizar_vehiculo(vehiculo_id, {"variante_id": variante["id"]})
    db.limpiar_estado(telegram_id)
    tg.enviar_mensaje(chat_id,
        f"✅ Variante actualizada a <b>{variante['nombre']}</b>. "
        f"Los intervalos e insumos se recalcularon.\nUsa /insumos o /proximo para verlos.")


# =====================================================================
# OTROS COMANDOS
# =====================================================================

def _comando_km(chat_id, telegram_id, usuario, args) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    if not args:
        tg.enviar_mensaje(chat_id, "Escríbelo así: <code>/km 46000</code>")
        return
    km = _a_entero(args[0])
    if km is None:
        tg.enviar_mensaje(chat_id, "El kilometraje debe ser un número. Ej: <code>/km 46000</code>")
        return
    db.actualizar_vehiculo(vehiculo["id"], {"kilometraje_actual": km,
                                            "fecha_actualizacion_km": db._hoy()})
    db.registrar_lectura_km(vehiculo["id"], km)
    tg.enviar_mensaje(chat_id, f"✅ Kilometraje actualizado a {km} km.")


def _comando_insumos(chat_id, usuario) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    v = db.obtener_variante(vehiculo["variante_id"])
    tg.enviar_mensaje(chat_id,
        f"🛢️ <b>Insumos de tu {v['nombre']}</b>\n"
        f"• Aceite de motor: {v['aceite_motor']} — {v['capacidad_aceite_l']} L\n"
        f"• Bujías: {v['bujia_tipo']}\n"
        f"• Transmisión: {v['liquido_transmision']} — {v['capacidad_transmision_l']} L\n"
        f"• Refrigerante: {v['refrigerante_l']} L\n"
        f"• Llantas: {v['medida_llanta']} — {v['presion_llantas']}")


def _comando_proximo(chat_id, usuario) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    estados = mantenimiento.calcular_estado_vehiculo(vehiculo)
    lineas = [mantenimiento.texto_estado(r) for r in estados]
    encabezado = (f"📋 <b>Próximos mantenimientos</b>\n"
                  f"Kilometraje actual: {vehiculo.get('kilometraje_actual',0)} km\n\n")
    tg.enviar_mensaje(chat_id, encabezado + "\n".join(lineas))


def _comando_registrar(chat_id, telegram_id, usuario) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    tipos = db.listar_tipos_mantenimiento()
    # Construimos botones de a dos por fila.
    filas, fila = [], []
    for t in tipos:
        fila.append((t["nombre"], f"tipo:{t['id']}"))
        if len(fila) == 2:
            filas.append(fila); fila = []
    if fila:
        filas.append(fila)
    db.guardar_estado(telegram_id, "mant_tipo", {})
    tg.enviar_mensaje(chat_id, "¿Qué mantenimiento realizaste?", teclado=tg.teclado_inline(filas))


def _finalizar_registro_mantenimiento(chat_id, telegram_id, usuario, datos) -> None:
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    db.crear_mantenimiento(
        vehiculo_id=vehiculo["id"],
        tipo_id=datos["tipo_id"],
        fecha=db._hoy(),
        kilometraje=datos["km"],
        costo=datos.get("costo") or None,
        taller=datos.get("taller"),
        notas=None,
    )
    # Si el kilometraje del servicio es mayor al registrado, actualizamos el del vehículo.
    if datos["km"] > (vehiculo.get("kilometraje_actual") or 0):
        db.actualizar_vehiculo(vehiculo["id"], {"kilometraje_actual": datos["km"],
                                                "fecha_actualizacion_km": db._hoy()})
        db.registrar_lectura_km(vehiculo["id"], datos["km"])
    tipo = db.obtener_tipo(datos["tipo_id"])
    db.limpiar_estado(telegram_id)
    tg.enviar_mensaje(chat_id,
        f"✅ Registrado: <b>{tipo['nombre']}</b> a los {datos['km']} km. ¡Gracias!")


def _comando_historial(chat_id, usuario) -> None:
    if not _exigir_aprobado(chat_id, usuario):
        return
    vehiculo = db.buscar_vehiculo_de_usuario(usuario["id"])
    registros = db.historial(vehiculo["id"])
    if not registros:
        tg.enviar_mensaje(chat_id, "Aún no tienes mantenimientos registrados. Usa /registrar.")
        return
    tipos = {t["id"]: t["nombre"] for t in db.listar_tipos_mantenimiento()}
    lineas = []
    for r in registros:
        nombre = tipos.get(r["tipo_mantenimiento_id"], "Mantenimiento")
        costo = f" · ${r['costo']}" if r.get("costo") else ""
        lineas.append(f"• {r['fecha']} — {nombre} ({r['kilometraje']} km){costo}")
    tg.enviar_mensaje(chat_id, "🧾 <b>Historial reciente</b>\n" + "\n".join(lineas))


def _comando_ayuda(chat_id, usuario) -> None:
    es_admin = usuario and usuario.get("rol") == "admin"
    texto = ("🤖 <b>Comandos disponibles</b>\n"
             "/start — Registrarme\n"
             "/perfil — Ver y modificar mi perfil\n"
             "/insumos — Aceite, bujía y líquidos de mi variante\n"
             "/proximo — Próximos mantenimientos\n"
             "/km 46000 — Actualizar kilometraje\n"
             "/registrar — Anotar un mantenimiento realizado\n"
             "/historial — Ver mantenimientos anteriores\n"
             "/cancelar — Cancelar la operación actual")
    if es_admin:
        texto += ("\n\n<b>Administrador</b>\n"
                  "/aprobar ID — Aprobar una solicitud\n"
                  "/rechazar ID — Rechazar una solicitud")
    tg.enviar_mensaje(chat_id, texto)


# =====================================================================
# ADMINISTRADOR
# =====================================================================

def _comando_admin(chat_id, telegram_id, comando, args) -> None:
    if telegram_id != ADMIN_TELEGRAM_ID:
        tg.enviar_mensaje(chat_id, "Este comando es solo para el administrador.")
        return
    if not args or _a_entero(args[0]) is None:
        tg.enviar_mensaje(chat_id, f"Uso: <code>{comando} ID_USUARIO</code>")
        return
    usuario_id = _a_entero(args[0])
    nuevo_estado = "aprobado" if comando == "/aprobar" else "rechazado"
    db.actualizar_usuario(usuario_id, {"estado": nuevo_estado})

    # Avisamos al usuario afectado.
    resp = db.supabase.table("usuarios").select("telegram_id").eq("id", usuario_id).execute()
    if resp.data:
        tid = resp.data[0]["telegram_id"]
        if nuevo_estado == "aprobado":
            tg.enviar_mensaje(tid, "🎉 ¡Tu cuenta fue aprobada! Escribe /ayuda para empezar.")
        else:
            tg.enviar_mensaje(tid, "Lamentablemente tu solicitud fue rechazada.")
    tg.enviar_mensaje(chat_id, f"Usuario {usuario_id} → <b>{nuevo_estado}</b>.")


# =====================================================================
# AYUDAS
# =====================================================================

def _exigir_aprobado(chat_id, usuario) -> bool:
    """Devuelve True si el usuario puede usar comandos; si no, avisa y devuelve False."""
    if not usuario:
        tg.enviar_mensaje(chat_id, "Primero regístrate con /start.")
        return False
    if usuario["estado"] != "aprobado":
        tg.enviar_mensaje(chat_id, "Tu cuenta aún no está aprobada. Espera la confirmación. 🙌")
        return False
    return True


def _a_entero(texto: str):
    """Convierte texto a entero de forma segura; devuelve None si no se puede."""
    try:
        return int(str(texto).replace(".", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _a_numero(texto: str):
    """Convierte texto a número decimal; devuelve None si no se puede."""
    try:
        return float(str(texto).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None
