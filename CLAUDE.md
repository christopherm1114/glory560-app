# glory560-app — contexto del proyecto

Aplicación de control de mantenimiento preventivo para el vehículo **DFSK Glory 560**,
en Guayaquil, Ecuador. Es el sistema que sustenta la tesis de tecnólogo en Redes y
Telecomunicaciones del autor (Instituto Superior Tecnológico Universitario Euroamericano).

## Arquitectura

Monolito **FastAPI** desplegado en **Render** (plan gratuito). Un solo proceso atiende
dos frentes: el *webhook* del bot de Telegram y un panel web de una sola página.
La persistencia está en **Supabase (PostgreSQL)**, accedida con el cliente oficial
`supabase-py` usando la clave `service_role`. Los recordatorios diarios los dispara
**cron-job.org** golpeando una ruta HTTP protegida por token.

```
Telegram ──────┐
Navegador ─────┼──▶ FastAPI (1 proceso) ──▶ Supabase (PostgreSQL)
cron-job.org ──┘                        └──▶ API de Telegram
```

Todos los archivos están en un solo nivel, sin carpetas. Fue una decisión deliberada
para simplificar la subida a GitHub por la interfaz web; conviene mantenerla salvo
que haya una razón fuerte para cambiarla.

| Archivo | Responsabilidad |
|---|---|
| `main.py` | Entrada ASGI. Rutas: `/`, `/webhook/telegram`, `/tasks/revisar-vencimientos`. |
| `config.py` | Variables de entorno, con error explícito si falta una obligatoria. |
| `db.py` | **Única** capa que habla con Supabase. Todo acceso a datos pasa por aquí. |
| `mantenimiento.py` | Motor de cálculo: decide si un control está vencido, próximo o al día. |
| `handlers.py` | Máquina de estados del bot de Telegram. |
| `web.py` | API REST del panel + rutas de administración. |
| `panel.html` | Frontend completo (HTML + CSS + JS, Chart.js por CDN). |
| `auth.py` | Contraseñas PBKDF2 y cookie de sesión firmada con HMAC. |
| `telegram.py` | Cliente de la API de Telegram. |
| `tareas.py` | Recordatorio diario de kilometraje. |
| `pruebas.py` | Pruebas de humo. No tocan Supabase ni Telegram; correrlas antes de fusionar. |
| `schema.sql` / `seed.sql` | Estructura y catálogo inicial. |

## Convenciones del código

- **Todo en español**: nombres de funciones, variables, comentarios y docstrings.
  Mantenerlo. Los *docstrings* explican el *porqué*, no solo el *qué*.
- **`db.py` es la única puerta a la base de datos.** Ni `web.py` ni `handlers.py` deben
  llamar a `supabase.table(...)` directamente. `tareas.py` ya se limpió; si aparece otra
  violación, moverla a `db.py`.
- `mantenimiento.py` no conoce Telegram ni HTTP. Es dominio puro. No introducir
  dependencias hacia arriba.
- Las funciones de `handlers.py` son **síncronas**; `main.py` las despacha con
  `BackgroundTasks`, que las corre en un hilo aparte. No convertirlas a `async`
  sin cambiar también el punto de llamada.
- **Ninguna ruta de `main.py` puede tardar en responder.** El webhook contesta 200 a
  Telegram *antes* de procesar (si tarda, Telegram reenvía el update y se duplican los
  registros), y `/tasks/revisar-vencimientos` devuelve `ok` de inmediato y trabaja en
  segundo plano (cron-job.org aborta a los ~30 s y desactiva los jobs que fallan).
- **`/salud` y `/tasks/revisar-vencimientos` son cosas distintas y deben seguir siéndolo.**
  `/salud` es el keep-alive que evita que Render duerma el servicio: barato, sin base de
  datos, sin envíos. La tarea manda mensajes reales a los usuarios. Mezclarlas obliga a
  elegir entre un servidor dormido o un usuario recibiendo recordatorios cada 10 minutos.
- Los catálogos (`tipos_mantenimiento`, `intervalos`) se sirven de una caché en memoria
  de 10 minutos (`db._cacheado`). Son de solo lectura: si alguna ruta llega a escribirlos,
  hay que llamar a `db.limpiar_cache()`.

## Modelo de datos

Catálogos de solo lectura (`variantes`, `tipos_mantenimiento`, `intervalos`) separados
de los datos personales (`usuarios`, `vehiculos`, `mantenimientos`, `lecturas_km`,
`alertas`, `estado_conversacion`).

El sistema distingue las **cuatro variantes** del Glory 560 — SFG18 5MT, SFG18 CVT,
SFG15T 6MT y SFG15T CVT — y ajusta bujías, aceite de transmisión e intervalos según
el manual del fabricante. Esa fidelidad al manual es el diferenciador del proyecto
frente a una app genérica de mantenimiento; conservarla al hacer cambios.

## Problemas conocidos (pendientes, en orden de prioridad)

1. **La cookie de sesión se firma con `TELEGRAM_BOT_TOKEN`** (`auth.crear_cookie_sesion`).
   Si ese token se filtra, se pueden fabricar sesiones válidas de cualquier usuario,
   admin incluido. Necesita un `SESSION_SECRET` propio.

2. **La contraseña inicial es el número de teléfono, guardada en claro** en
   `usuarios.clave` (`db.crear_usuario`). `auth.verificar_credencial` acepta como válida
   la comparación de los últimos 9 dígitos del teléfono. Hay que forzar el cambio de
   contraseña en el primer ingreso y luego eliminar la columna `clave`.

3. **`supabase-py 2.7.4` solo acepta claves con formato JWT.** Valida la clave contra una
   expresión regular de tres segmentos separados por puntos (ver `supabase/_sync/client.py`).
   Las claves nuevas de Supabase (`sb_secret_...`) **no pasan** esa validación: el proceso
   muere al arrancar con `SupabaseException: Invalid API key`. Mientras la clave sea la JWT
   antigua (`eyJ...`) funciona, pero Supabase está retirando ese formato. Antes de rotar la
   clave hay que subir `supabase-py`. Ojo: `LEEME.md` todavía manda usar la clave nueva.

4. **Consultas que descargan tablas completas.**
   `db.buscar_usuario_por_telefono_normalizado` trae toda la tabla `usuarios` y filtra en
   Python — en cada login. `db.promedios_por_tipo` trae todos los mantenimientos de todos
   los usuarios en cada carga del panel.
   Solución: columna `telefono_normalizado` indexada, y agregaciones en Postgres.

5. **La tabla `alertas` está definida pero nadie la usa.** `db.crear_alerta` y
   `db.alerta_reciente_existe` —esta última con lógica anti-spam de 7 días— no se llaman
   desde ningún lado. Decidir: cablearlas o sacarlas del esquema.

6. Menores: `_a_entero` convierte `"45.5"` en `455`; los meses se aproximan como bloques
   de 30 días (~5 días de desfase al año); la sesión expira a los 12 minutos de inactividad.

### Resueltos (no volver a introducirlos)

- `schema.sql` volvió a estar al día, y `migrations/001_alinear_esquema.sql` pone al día
  una base vieja. **Verificar que 001 se haya ejecutado en el Supabase real**: si no,
  la pestaña Recomendaciones sale vacía y el "tip del día" nunca se envía.
- El keep-alive vive en `/salud`, separado de la tarea de recordatorios.
- El webhook responde 200 antes de procesar, así Telegram no reenvía updates duplicados.
- La tarea usa `TASKS_TOKEN` propio (con respaldo al secreto del webhook) y acepta
  la cabecera `X-Tasks-Token`.
- Un vehículo sin historial parte de su kilometraje de registro, no de 0
  (`db.km_base_vehiculo`), así que ya no aparece todo en rojo el primer día.
- Los comandos del bot avisan si el usuario no tiene vehículo, en vez de fallar en
  silencio; `procesar_update` registra la traza completa y le responde al usuario.

## Seguridad y despliegue

- **Nunca** subir el `.env`. El `.gitignore` estuvo un tiempo subido con el nombre
  equivocado (`download`); si vuelve a aparecer así, renombrarlo de inmediato.
- Variables de entorno requeridas: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ADMIN_TELEGRAM_ID`. Opcional pero recomendada:
  `TASKS_TOKEN` (si falta, la tarea cae al secreto del webhook y lo avisa en el log).
- **Cron:** dos trabajos distintos. `GET /salud` cada 10 minutos (mantiene despierto el
  servicio de Render, que duerme a los 15 minutos sin tráfico) y
  `GET /tasks/revisar-vencimientos` con el token, una vez al día a las 08:00.
- La clave de Supabase es `service_role`: **ignora RLS por completo**. Toda la
  autorización descansa en `web._usuario_actual` y `web._solo_admin`. Al agregar
  cualquier ruta nueva a `web.py`, la primera línea debe ser una de esas dos
  comprobaciones. Un olvido expone los datos de todos los usuarios.
- Si Render está en auto-deploy desde `main`, cada push va directo a producción.
  Trabajar en una rama y fusionar solo lo verificado.

## Entorno local

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

El panel queda en `http://localhost:8000/panel`. El webhook del bot **no** funciona en
local: Telegram necesita una URL pública. Para probar el bot hace falta un túnel
(ngrok o similar) y reconfigurar el webhook, o probar directamente contra Render.

Cuidado: por defecto el `.env` local apunta al **mismo Supabase de producción**.
Conviene crear un segundo proyecto en Supabase para desarrollo.
