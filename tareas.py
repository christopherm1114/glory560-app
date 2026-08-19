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

import db
import telegram as tg
import mantenimiento


def revisar_vencimientos() -> int:
    """Envía los recordatorios pendientes y devuelve cuántos envió."""
    hoy = db._hoy()
    enviados = 0

    for vehiculo in db.listar_todos_los_vehiculos():
        # 1) El dueño debe existir y estar aprobado.
        resp = db.supabase.table("usuarios").select("*").eq("id", vehiculo["usuario_id"]).execute()
        if not resp.data:
            continue
        usuario = resp.data[0]
        if usuario.get("estado") != "aprobado":
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


if __name__ == "__main__":
    total = revisar_vencimientos()
    print(f"Recordatorios enviados: {total}")
