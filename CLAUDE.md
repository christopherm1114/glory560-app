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
| `schema.sql` / `seed.sql` | Estructura y catálogo inicial. |

## Convenciones del código

- **Todo en español**: nombres de funciones, variables, comentarios y docstrings.
  Mantenerlo. Los *docstrings* explican el *porqué*, no solo el *qué*.
- **`db.py` es la única puerta a la base de datos.** Ni `web.py` ni `handlers.py` deben
  llamar a `supabase.table(...)` directamente. Hay un par de violaciones heredadas en
  `tareas.py` y `handlers.py` — al tocarlas, moverlas a `db.py`.
- `mantenimiento.py` no conoce Telegram ni HTTP. Es dominio puro. No introducir
  dependencias hacia arriba. El cálculo vive en `calcular_estado()`, que **no consulta
  la base de datos**: recibe los datos ya leídos y la fecha como argumentos, por eso se
  puede probar. `calcular_estado_vehiculo()` es el envoltorio delgado que lee de `db` y
  delega. Al ampliar el motor, la lógica va en la función pura y su prueba.
- Las funciones de `handlers.py` son **síncronas**; `main.py` las ejecuta con
  `run_in_threadpool` para no bloquear el bucle asíncrono. No convertirlas a `async`
  sin cambiar también el punto de llamada.
- La ruta `/tasks/revisar-vencimientos` debe devolver **siempre** texto plano corto,
  incluso ante un error. El plan gratuito de cron-job.org corta las respuestas grandes.

## Modelo de datos

Catálogos de solo lectura (`variantes`, `tipos_mantenimiento`, `intervalos`) separados
de los datos personales (`usuarios`, `vehiculos`, `mantenimientos`, `lecturas_km`,
`alertas`, `estado_conversacion`).

El sistema distingue las **cuatro variantes** del Glory 560 — SFG18 5MT, SFG18 CVT,
SFG15T 6MT y SFG15T CVT — y ajusta bujías, aceite de transmisión e intervalos según
el manual del fabricante. Esa fidelidad al manual es el diferenciador del proyecto
frente a una app genérica de mantenimiento; conservarla al hacer cambios.

## Problemas conocidos (pendientes, en orden de prioridad)

1. **`schema.sql` está desfasado del código.** Faltan la tabla `lecturas_km` completa y
   las columnas `usuarios.clave`, `usuarios.clave_hash`, `usuarios.reset_codigo`,
   `usuarios.reset_expira`, `mantenimientos.creado_en`, `tipos_mantenimiento.clase`,
   `tipos_mantenimiento.mercado_min/mercado_max/mercado_nota`. Quien clone el repo y
   ejecute `schema.sql` obtiene una app rota. Hay que regenerarlo desde el Supabase real
   y, de ahí en adelante, versionar los cambios como `migrations/00X_*.sql`.
   *Efecto silencioso:* como `tipos_mantenimiento.clase` no existe, la pestaña
   **Recomendaciones del panel siempre sale vacía** y el "tip del día" nunca se envía.

2. ~~**La cookie de sesión se firma con `TELEGRAM_BOT_TOKEN`**~~ — *resuelto*. Ahora se
   firma con `SESSION_SECRET`, propio de la aplicación. Las dos mitades del mecanismo
   (`auth.crear_cookie_sesion` y `auth.leer_cookie_sesion`) solo están unidas por esa
   constante de módulo: al cambiarla hay que tocar **ambas** o nadie puede iniciar sesión.

3. **La contraseña inicial es el número de teléfono, guardada en claro** en
   `usuarios.clave` (`db.crear_usuario`). `auth.verificar_credencial` acepta como válida
   la comparación de los últimos 9 dígitos del teléfono. Hay que forzar el cambio de
   contraseña en el primer ingreso y luego eliminar la columna `clave`.

4. ~~**El token de la tarea viaja en la URL**~~ — *resuelto*. Ahora es un `TASKS_TOKEN`
   propio que viaja en la cabecera `X-Tasks-Token`. Al mismo tiempo se cerró un fallo
   más grave que no estaba documentado: `TELEGRAM_WEBHOOK_SECRET` era opcional y las dos
   comprobaciones tenían la forma `if SECRETO and valor != SECRETO`, así que con la
   variable sin definir **el webhook y la tarea quedaban completamente abiertos**. Las
   tres variables son ahora obligatorias y se comparan con `hmac.compare_digest`.

5. **Consultas que descargan tablas completas.**
   `db.buscar_usuario_por_telefono_normalizado` trae toda la tabla `usuarios` y filtra en
   Python — en cada login. `db.promedios_por_tipo` trae todos los mantenimientos de todos
   los usuarios en cada carga del panel. `tareas.py` consulta `usuarios` dentro del bucle.
   Solución: columna `telefono_normalizado` indexada, y agregaciones en Postgres.

6. ~~**Un vehículo sin historial aparece con todo vencido.**~~ — *resuelto*. La línea base
   es ahora `vehiculos.kilometraje_inicial`, congelado en el alta (migración `002`). No
   sirve usar `kilometraje_actual`: al subir con el odómetro, el objetivo se aleja y el
   control no vencería nunca. Cubierto por `test_mantenimiento.py`.

7. **La tabla `alertas` está definida pero nadie la usa.** `db.crear_alerta` y
   `db.alerta_reciente_existe` —esta última con lógica anti-spam de 7 días— no se llaman
   desde ningún lado. Decidir: cablearlas o sacarlas del esquema.

8. Menores: `_a_entero` convierte `"45.5"` en `455`; los meses se aproximan como bloques
   de 30 días (~5 días de desfase al año); la sesión expira a los 12 minutos de inactividad.

## Seguridad y despliegue

- **Nunca** subir el `.env`. El `.gitignore` estuvo un tiempo subido con el nombre
  equivocado (`download`); si vuelve a aparecer así, renombrarlo de inmediato.
- Variables de entorno requeridas: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `SESSION_SECRET`, `TASKS_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
  `ADMIN_TELEGRAM_ID`. Un secreto por frontera de confianza: no reutilizar uno para
  dos usos. Todas salvo `ADMIN_TELEGRAM_ID` pasan por `config._requerida`, así que si
  falta alguna la app no arranca — eso es deliberado, es preferible a fallar en abierto.
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

Para las pruebas:

```powershell
pip install -r requirements-dev.txt
pytest
```

No necesitan credenciales ni base de datos: `conftest.py` aísla el import de `db`, y el
motor de cálculo recibe los datos como argumentos.

El panel queda en `http://localhost:8000/panel`. El webhook del bot **no** funciona en
local: Telegram necesita una URL pública. Para probar el bot hace falta un túnel
(ngrok o similar) y reconfigurar el webhook, o probar directamente contra Render.

Cuidado: por defecto el `.env` local apunta al **mismo Supabase de producción**.
Conviene crear un segundo proyecto en Supabase para desarrollo.
