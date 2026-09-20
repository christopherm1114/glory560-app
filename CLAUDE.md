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
- **El odómetro nunca retrocede por `/km`.** La vía de corrección de un dato mal tecleado
  es `/perfil` en el bot o el perfil del panel; ahí sí se permite bajarlo. Un servicio,
  en cambio, sí puede registrarse a menos km que el odómetro (se hizo en el pasado), pero
  nunca a más. Las dos reglas viven en `mantenimiento.py`, que es dominio puro.
- **`panel.html` lee por nombre los campos que arma `web._resumen_vehiculo`**, sin tipos ni
  esquema de por medio: renombrar uno rompe la pantalla en silencio. `pruebas.py` fija ese
  contrato en `CAMPOS_SEMAFORO` y `CAMPOS_RECOMENDACION`; si cambias un campo, cámbialo ahí.

## Modelo de datos

Catálogos de solo lectura (`variantes`, `tipos_mantenimiento`, `intervalos`) separados
de los datos personales (`usuarios`, `vehiculos`, `mantenimientos`, `lecturas_km`,
`alertas`, `estado_conversacion`).

El sistema distingue las **cuatro variantes** del Glory 560 — SFG18 5MT, SFG18 CVT,
SFG15T 6MT y SFG15T CVT — y ajusta bujías, aceite de transmisión e intervalos según
el manual del fabricante. Esa fidelidad al manual es el diferenciador del proyecto
frente a una app genérica de mantenimiento; conservarla al hacer cambios.

## Problemas conocidos (pendientes, en orden de prioridad)

1. **La clave `service_role` anula RLS: toda la autorización vive en el código.** Es el
   único hallazgo de la auditoría que sigue abierto, y no es un descuido sino un rediseño:
   la app tiene su propia autenticación (cookie firmada), así que Postgres no sabe quién
   es el usuario y no puede aplicar políticas por fila. Resolverlo de verdad exige adoptar
   Supabase Auth o emitir JWT por usuario firmados con el secreto del proyecto, y recién
   entonces migrar a la clave `anon` con RLS. Mientras tanto la defensa es la disciplina:
   **la primera línea de toda ruta nueva en `web.py` debe ser `_usuario_actual` o
   `_solo_admin`.** Las 20 rutas actuales cumplen; `pruebas.py` no lo verifica todavía.

2. **Terminar de retirar la contraseña heredada.** El cambio ya es obligatorio en la
   práctica, pero la columna `usuarios.clave` sigue existiendo y `auth.verificar_credencial`
   conserva la rama que acepta el teléfono. Cuando los tres usuarios hayan definido su
   contraseña: quitar esa rama y ejecutar `ALTER TABLE usuarios DROP COLUMN clave`.

3. **`supabase-py 2.7.4` solo acepta claves con formato JWT.** Las claves nuevas de
   Supabase (`sb_secret_...`) no pasan su validación y el proceso muere al arrancar con
   `SupabaseException: Invalid API key`. Antes de rotar la clave hay que subir la librería.

4. **Datos sucios heredados en producción.** El bug de `_a_entero` (corregido) dejó lecturas
   diez veces mayores de lo tecleado. El vehículo GPZ0327 arrastra además una primera
   lectura de 5.000 km —de prueba— que es su línea base, y un servicio registrado a
   105.000 km con el odómetro en 47.300, por lo que muestra 27 controles vencidos aunque
   el código sea correcto. Limpiarlo son escrituras sobre producción: preguntar antes.

5. **La tabla `alertas` está definida pero nadie la usa.** `db.crear_alerta` y
   `db.alerta_reciente_existe` no se llaman desde ningún lado. Decidir: cablearlas o
   sacarlas del esquema.

6. Menores: los meses se aproximan como bloques de 30 días (~5 días de desfase al año);
   la sesión expira a los 12 minutos de inactividad; el limitador de intentos vive en
   memoria, así que se reinicia con el proceso y no se comparte entre instancias.

### Resueltos (no volver a introducirlos)

- El keep-alive vive en `/salud`, separado de la tarea de recordatorios.
- El webhook responde 200 antes de procesar: Telegram no reenvía updates duplicados.
- `TASKS_TOKEN` y `SESSION_SECRET` propios, con respaldo y aviso en el log si faltan.
- Línea base de kilometraje = primera lectura por fecha (`db.km_base_vehiculo`).
- Las conversaciones del bot caducan a las 6 horas.
- `_a_entero` entiende la notación local: `3861.5` ya no se guarda como `38615`.
- El kilometraje se valida al entrar, en el bot y en el panel.
- **XSS:** `panel.html` escapa con `esc()` todo lo que viene del servidor, y el botón de
  precio de mercado pasa sus datos por `data-*` en vez de por el `onclick`.
- **Fuerza bruta:** limitador por IP y por cuenta en login y recuperación (`auth.py`).
- **Cabeceras:** CSP, HSTS, X-Frame-Options y compañía, en un middleware de `main.py`.
- **Sesiones:** la cookie lleva una marca de la contraseña vigente, así que cambiarla
  invalida las sesiones abiertas.
- **Contraseña inicial:** las cuentas nuevas no nacen con el teléfono como clave, y la
  sesión heredada solo sirve para definir una contraseña propia.
- **Consultas:** con `migrations/002` el login resuelve con un índice y los promedios los
  calcula Postgres. `db.py` detecta si la migración está aplicada y usa el camino antiguo
  si no, así que desplegar y migrar no tienen que coincidir en el tiempo.

## Seguridad y despliegue

- **Nunca** subir el `.env`. El `.gitignore` estuvo un tiempo subido con el nombre
  equivocado (`download`); si vuelve a aparecer así, renombrarlo de inmediato.
- Variables de entorno requeridas: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ADMIN_TELEGRAM_ID`. Opcional pero recomendada:
  `TASKS_TOKEN` y `SESSION_SECRET` (si faltan, caen al secreto del webhook y al token del
  bot respectivamente, y lo avisan en el log).
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
