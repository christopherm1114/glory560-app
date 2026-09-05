# Graph Report - glory560-app  (2026-09-05)

## Corpus Check
- Corpus is ~13,634 words - fits in a single context window. You may not need a graph.

## Summary
- 286 nodes · 618 edges · 12 communities (9 shown, 2 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.85)
- Token cost: 128,666 input · 9,500 output

## Community Hubs (Navigation)
- Bot de Telegram y Dominio del Vehiculo
- Autenticacion y Recuperacion de Clave
- Acceso a Datos y Motor de Mantenimiento
- API REST del Panel y Roles
- Frontend del Panel (Vistas)
- Despliegue, Sesion y Deuda de Seguridad
- Entrada ASGI y Configuracion
- Cliente de la API de Telegram
- Esquema de Base de Datos
- Migracion y Desfase de Esquema
- Detalle de Registro (aislado)

## God Nodes (most connected - your core abstractions)
1. `enviar_mensaje()` - 27 edges
2. `buscar_vehiculo_de_usuario()` - 17 edges
3. `_usuario_actual()` - 15 edges
4. `abrirTab (enrutador de vistas)` - 15 edges
5. `_manejar_comando()` - 14 edges
6. `calcular_estado_vehiculo()` - 13 edges
7. `_resumen_vehiculo()` - 13 edges
8. `_continuar_conversacion()` - 12 edges
9. `_manejar_callback()` - 12 edges
10. `_solo_admin()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Viñetas condicionadas por rol (admin vs usuario)` --conceptually_related_to--> `_solo_admin()`  [INFERRED]
  panel.html → web.py
- `precioProm` --shares_data_with--> `promedios_por_tipo()`  [INFERRED]
  panel.html → db.py
- `Fidelidad a las cuatro variantes del Glory 560` --conceptually_related_to--> `calcular_estado_vehiculo()`  [INFERRED]
  CLAUDE.md → mantenimiento.py
- `vistaMant (mantenimientos próximos)` --references--> `calcular_estado_vehiculo()`  [INFERRED]
  panel.html → mantenimiento.py
- `vistaMant (mantenimientos próximos)` --shares_data_with--> `_resumen_vehiculo()`  [INFERRED]
  panel.html → web.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Flujo de sesión del panel (login, latido, cierre por inactividad)** — panel_iniciar, panel_hacerlogin, panel_mostrarlogin, panel_logout, panel_iniciarinactividad, panel_reiniciaridle, panel_cerrarporinactividad [EXTRACTED 1.00]
- **Flujo de recuperación de contraseña en dos pasos** — panel_verrecuperar, panel_pedircodigo, panel_confirmarrecuperacion, panel_mensajeerror, panel_verlogin, panel_recuperacion_contrasena [EXTRACTED 1.00]
- **Renderizado del semáforo y sus precios** — panel_vistamant, panel_pintarsemaforo, panel_filasemaforo, panel_precioprom, panel_vermercado, panel_orden_cat, panel_verusuario [EXTRACTED 1.00]
- **Deuda de seguridad del panel y las tareas** — claude_problema_cookie_firmada_con_token_bot, claude_problema_clave_inicial_en_claro, claude_problema_token_tarea_en_url, claude_autorizacion_service_role_sin_rls, claude_gitignore_nombre_incorrecto [INFERRED 0.85]
- **Pila de despliegue en el plan gratuito de Render** — render_servicio_glory560_bot, render_start_command_uvicorn, render_envvars_sync_false, requirements_fastapi, requirements_uvicorn, claude_recordatorio_diario_cronjob [INFERRED 0.85]
- **Aplanado del repositorio y sus consecuencias operativas** — claude_estructura_plana_archivos, leeme_version_archivos_planos, leeme_migracion_api_main_a_main, render_start_command_uvicorn, claude_gitignore_nombre_incorrecto [INFERRED 0.85]

## Communities (12 total, 2 thin omitted)

### Community 0 - "Bot de Telegram y Dominio del Vehiculo"
Cohesion: 0.08
Nodes (66): Fidelidad a las cuatro variantes del Glory 560, mantenimiento.py como dominio puro, Separacion catalogos de solo lectura vs datos personales, Problema 6: vehiculo sin historial aparece con todo vencido, Problema 8: defectos menores acumulados, actualizar_vehiculo(), buscar_usuario_por_telegram(), buscar_variante() (+58 more)

### Community 1 - "Autenticacion y Recuperacion de Clave"
Cohesion: 0.05
Nodes (45): contrasena_valida(), generar_codigo(), hash_password(), leer_cookie_sesion(), normalizar_telefono(), auth.py ------- Seguridad de la web: login por teléfono/contraseña y manejo de…, Verifica la cookie y devuelve el usuario_id si es válida y no expiró., Deja solo los dígitos, para que '+593 99...' y '09 9...' se comparen igual. (+37 more)

### Community 2 - "Acceso a Datos y Motor de Mantenimiento"
Cohesion: 0.07
Nodes (34): Problema 7: tabla alertas definida pero sin uso, date, _ahora_iso(), alerta_reciente_existe(), buscar_usuario_por_telefono(), buscar_usuarios(), crear_alerta(), crear_mantenimiento() (+26 more)

### Community 3 - "API REST del Panel y Roles"
Cohesion: 0.17
Nodes (31): Autorizacion en la aplicacion porque service_role ignora RLS, actualizar_usuario(), obtener_usuario(), buscarRoles, cambiarRol, hacerLogin, vistaRoles, api_aprobaciones() (+23 more)

### Community 4 - "Frontend del Panel (Vistas)"
Cohesion: 0.11
Nodes (32): abrirFormMant, abrirTab (enrutador de vistas), aprobar, cerrarModal, Chart.js por CDN (gráficos de kilometraje), construirTabs, Caché de estado del cliente (SESION, DATOS, TIPOS, REG_LISTA), eliminarMant (+24 more)

### Community 5 - "Despliegue, Sesion y Deuda de Seguridad"
Cohesion: 0.07
Nodes (31): crear_cookie_sesion(), Crea un texto firmado 'usuario_id.expiracion.firma' (sesión corta y deslizante)., Arquitectura: monolito FastAPI de un solo proceso, Convencion: todo el codigo en espanol, Entorno local y limitacion del webhook, Estructura de archivos plana (sin carpetas), Riesgo: .gitignore subido con el nombre equivocado, Problema 2: cookie de sesion firmada con TELEGRAM_BOT_TOKEN (+23 more)

### Community 6 - "Entrada ASGI y Configuracion"
Cohesion: 0.16
Nodes (12): config.py --------- Lee las variables de entorno (los "secretos" y ajustes de…, Obtiene una variable obligatoria; si falta, avisa con un error claro., _requerida(), get, post, Request, main.py ------- El punto de entrada de la aplicación web (FastAPI). Aquí se…, Ruta simple para verificar que el servicio está funcionando. (+4 more)

### Community 7 - "Cliente de la API de Telegram"
Cohesion: 0.20
Nodes (11): boton_compartir_telefono(), configurar_webhook(), _llamar(), quitar_teclado(), telegram.py ----------- Funciones para HABLAR con Telegram (enviar mensajes,…, Hace una petición POST a la API de Telegram y devuelve la respuesta., Cuando el usuario toca un botón "inline", Telegram espera una confirmación.…, Teclado especial que pide al usuario compartir su número de teléfono. Telegram… (+3 more)

### Community 8 - "Esquema de Base de Datos"
Cohesion: 0.40
Nodes (9): alertas, estado_conversacion, intervalos, lecturas_km, mantenimientos, tipos_mantenimiento, usuarios, variantes (+1 more)

## Knowledge Gaps
- **13 isolated node(s):** `estado_conversacion`, `verRegistro`, `verRecuperar`, `verLogin`, `hacerLogin` (+8 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 83 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `crear_cookie_sesion()` connect `Despliegue, Sesion y Deuda de Seguridad` to `Autenticacion y Recuperacion de Clave`, `API REST del Panel y Roles`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **What connects `estado_conversacion`, `verRegistro`, `verRecuperar` to the rest of the system?**
  _13 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Bot de Telegram y Dominio del Vehiculo` be split into smaller, more focused modules?**
  _Cohesion score 0.07643600180913614 - nodes in this community are weakly interconnected._
- **Should `Autenticacion y Recuperacion de Clave` be split into smaller, more focused modules?**
  _Cohesion score 0.05410628019323672 - nodes in this community are weakly interconnected._
- **Should `Acceso a Datos y Motor de Mantenimiento` be split into smaller, more focused modules?**
  _Cohesion score 0.06606606606606606 - nodes in this community are weakly interconnected._
- **Should `Frontend del Panel (Vistas)` be split into smaller, more focused modules?**
  _Cohesion score 0.10887096774193548 - nodes in this community are weakly interconnected._
- **Should `Despliegue, Sesion y Deuda de Seguridad` be split into smaller, more focused modules?**
  _Cohesion score 0.07311827956989247 - nodes in this community are weakly interconnected._