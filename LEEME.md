# 🚗 Glory 560 — Versión de archivos planos (fácil de subir a GitHub)

Esta versión tiene **todos los archivos en un solo nivel** (sin carpetas), para que subirla a GitHub sea sencillo: solo arrastras todos los archivos sueltos y listo.

## Cómo subir a GitHub (por la web)

1. Entra a tu repositorio en GitHub → "Add file" → **"Upload files"**.
2. Si ya tenías archivos cargados de un intento anterior, quítalos con la ✕ y empieza limpio.
3. Arrastra **todos** estos archivos (sueltos, sin carpetas):
   `config.py`, `telegram.py`, `db.py`, `mantenimiento.py`, `handlers.py`,
   `tareas.py`, `main.py`, `requirements.txt`, `render.yaml`,
   `schema.sql`, `seed.sql`.
4. Haz clic en **"Commit changes"**.

> Los archivos `schema.sql` y `seed.sql` son solo para copiarlos en Supabase (como ya hiciste). Que estén en GitHub no molesta.
> No subas ningún archivo `.env` (tus secretos).

## Qué cambió respecto a la versión con carpetas

- Antes: `api/main.py` → Ahora: `main.py` (todo suelto).
- En Render, el comando de arranque ahora es `uvicorn main:app` (ya viene así en `render.yaml`).
- El resto funciona exactamente igual. Los pasos de Supabase, Render y el webhook son los mismos de la guía anterior.

## Recordatorio de los valores que necesitas en Render

| Variable | De dónde sale |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather (al crear el bot) |
| `TELEGRAM_WEBHOOK_SECRET` | una palabra secreta que tú inventas |
| `SUPABASE_URL` | Supabase → Data API (o botón Connect) |
| `SUPABASE_SERVICE_KEY` | Supabase → API Keys → **Secret key** (`sb_secret_...`) |
| `ADMIN_TELEGRAM_ID` | @userinfobot (tu ID numérico) |
