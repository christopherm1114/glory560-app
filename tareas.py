"""
tareas.py
---------
Tareas programadas (se ejecutan solas, sin que nadie escriba al bot).

La principal es 'revisar_vencimientos': recorre todos los vehículos, calcula
qué mantenimientos están vencidos o próximos, y envía un recordatorio por
Telegram al dueño. El cron job de Render la ejecuta una vez al día.

También se puede ejecutar a mano con:  python -m api.tareas
"""

import db
import telegram as tg
import mantenimiento


def revisar_vencimientos() -> int:
    """Envía recordatorios y devuelve cuántas alertas mandó."""
    enviadas = 0
    for vehiculo in db.listar_todos_los_vehiculos():
        # Buscamos al dueño y verificamos que esté aprobado.
        resp = db.supabase.table("usuarios").select("*").eq("id", vehiculo["usuario_id"]).execute()
        if not resp.data:
            continue
        usuario = resp.data[0]
        if usuario["estado"] != "aprobado":
            continue

        estados = mantenimiento.calcular_estado_vehiculo(vehiculo)
        # Solo nos interesan los que están vencidos o próximos.
        urgentes = [r for r in estados if r["estado"] in ("vencido", "proximo")]
        if not urgentes:
            continue

        lineas = []
        for r in urgentes:
            # Para no repetir el mismo recordatorio a diario, saltamos los que
            # ya tienen una alerta 'enviada'.
            if db.alerta_reciente_existe(vehiculo["id"], r["tipo_id"]):
                continue
            lineas.append(mantenimiento.texto_estado(r))
            db.crear_alerta(vehiculo["id"], r["tipo_id"], db._hoy())

        if lineas:
            tg.enviar_mensaje(usuario["telegram_id"],
                "🔔 <b>Recordatorio de mantenimiento</b>\n"
                f"Tu {vehiculo.get('placa','vehículo')} necesita atención:\n\n"
                + "\n".join(lineas)
                + "\n\nCuando lo hagas, regístralo con /registrar.")
            enviadas += 1
    return enviadas


if __name__ == "__main__":
    # Esto se ejecuta cuando corremos: python -m api.tareas
    total = revisar_vencimientos()
    print(f"Recordatorios enviados: {total}")
