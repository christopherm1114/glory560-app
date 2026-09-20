"""
tareas.py
---------
Recordatorios automáticos (los llama cron-job.org).

Lógica:
  - Cada día a las 08:00 se envía un recordatorio pidiendo registrar el
    kilometraje del vehículo (y se listan los mantenimientos pendientes).
  - Mientras el usuario NO registre el kilometraje ESE día, se vuelve a
    insistir cada 2 horas (según la frecuencia configurada en cron-job.org).
  - Apenas el usuario registra el kilometraje (con /km en el bot o desde la
    web), la app deja de insistir hasta el día siguiente.

La "señal" de que ya cumplió es el campo fecha_actualizacion_km del vehículo:
si es igual a hoy, ya ingresó el kilometraje y no se le molesta más ese día.

Se puede ejecutar a mano con:  python tareas.py
"""

import random
import threading
import traceback

import db
import telegram as tg
import mantenimiento


# Evita que dos ejecuciones del cron se pisen. Si el servicio venía dormido,
# cron-job.org puede reintentar mientras la primera corrida sigue enviando
# mensajes; sin este candado el usuario recibiría el recordatorio por duplicado.
_candado = threading.Lock()


def ejecutar_revision() -> None:
    """
    Envoltorio que usa la ruta HTTP: corre la revisión en segundo plano,
    ignora la llamada si ya hay una en curso y nunca deja escapar un error
    (la ruta ya respondió; una excepción aquí solo ensuciaría el log).
    """
    if not _candado.acquire(blocking=False):
        print("[tareas] ya hay una revisión en curso; se ignora esta llamada")
        return
    try:
        total = revisar_vencimientos()
        print(f"[tareas] recordatorios enviados: {total}")
    except Exception as e:
        print(f"[tareas] error al revisar vencimientos: {e}")
        traceback.print_exc()
        tg.avisar_al_admin("La tarea de recordatorios falló", traceback.format_exc())
    finally:
        _candado.release()


def revisar_vencimientos() -> int:
    """Envía los recordatorios pendientes y devuelve cuántos envió."""
    hoy = db._hoy()
    enviados = 0

    # Los dueños se traen de UNA vez y se indexan por id. Antes se consultaba
    # la tabla 'usuarios' dentro del bucle: con N vehículos eran N consultas
    # extra, y eso era parte de por qué la tarea excedía el tiempo del cron.
    aprobados = {u["id"]: u for u in db.listar_usuarios_aprobados()}

    for vehiculo in db.listar_todos_los_vehiculos():
        # 1) El dueño debe existir y estar aprobado.
        usuario = aprobados.get(vehiculo["usuario_id"])
        if not usuario:
            continue

        # 2) ¿Ya registró el kilometraje HOY? Si sí, no insistimos.
        if str(vehiculo.get("fecha_actualizacion_km")) == hoy:
            continue

        # 3) Armamos el mensaje: recordar registrar el km + pendientes.
        estados = mantenimiento.calcular_estado_vehiculo(vehiculo)
        urgentes = [r for r in estados if r["estado"] in ("vencido", "proximo")]

        placa = vehiculo.get("placa", "tu vehículo")
        mensaje = (
            "🔔 <b>Recordatorio diario</b>\n"
            f"Registra el kilometraje de <b>{placa}</b> con "
            "<code>/km &lt;número&gt;</code> para mantener tu control al día."
        )
        if urgentes:
            lineas = "\n".join(mantenimiento.texto_estado(r) for r in urgentes)
            mensaje += "\n\n⚠️ <b>Mantenimientos por atender:</b>\n" + lineas
        else:
            mensaje += "\n\n🟢 Por ahora no tienes mantenimientos vencidos."

        # Tip aleatorio del día (de las recomendaciones de revisión).
        tips = [r for r in estados if r.get("clase") == "inspeccion" and r.get("intervalo_km")]
        if tips:
            t = random.choice(tips)
            km_txt = f"{t['intervalo_km']:,}".replace(",", ".")
            mensaje += (f"\n\n💡 <b>Tip del día:</b> recuerda que <b>{t['nombre']}</b> "
                        f"se lo revisa cada {km_txt} km. ¡Un buen conductor lo tiene presente! 🚗")

        try:
            tg.enviar_mensaje(usuario["telegram_id"], mensaje)
            enviados += 1
        except Exception as e:
            print(f"[tareas] No se pudo avisar al usuario {usuario.get('id')}: {e}")

    return enviados


# =====================================================================
# RESPALDO
# =====================================================================

_candado_respaldo = threading.Lock()


def ejecutar_respaldo() -> None:
    """
    Exporta la base y se la envía al administrador por Telegram.

    El respaldo acaba fuera del servidor, en un sitio al que el administrador
    siempre tiene acceso y que no depende del plan gratuito de la base de
    datos. Antes no existía ninguna copia: un borrado accidental en el editor
    SQL se llevaba por delante todo el historial.
    """
    import json
    from config import ADMIN_TELEGRAM_ID

    if not _candado_respaldo.acquire(blocking=False):
        print("[respaldo] ya hay uno en curso; se ignora esta llamada")
        return
    try:
        if not ADMIN_TELEGRAM_ID:
            print("[respaldo] falta ADMIN_TELEGRAM_ID; no hay a quien enviarlo")
            return
        volcado = db.exportar_todo()
        contenido = json.dumps(volcado, ensure_ascii=False, indent=1).encode("utf-8")
        nombre = f"respaldo-glory560-{db._hoy()}.json"
        resumen = " · ".join(f"{t}: {n}" for t, n in volcado["resumen"].items())
        tg.enviar_documento(
            ADMIN_TELEGRAM_ID, nombre, contenido,
            f"💾 <b>Respaldo {db._hoy()}</b>\n{resumen}\n"
            f"{len(contenido) / 1024:.0f} KB")
        print(f"[respaldo] enviado: {nombre} ({len(contenido)} bytes)")
    except Exception as e:
        print(f"[respaldo] error: {e}")
        traceback.print_exc()
        tg.avisar_al_admin("El respaldo automático falló", traceback.format_exc())
    finally:
        _candado_respaldo.release()


if __name__ == "__main__":
    total = revisar_vencimientos()
    print(f"Recordatorios enviados: {total}")
