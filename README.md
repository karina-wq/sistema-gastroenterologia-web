# Sistema de control de pacientes · Gastroenterología · Hospital Nacional Arzobispo Loayza (2026)

Aplicación web (Flask + PostgreSQL en Neon). La lógica clínica, los permisos, la auditoría y los
indicadores están en el paquete `sistema/` (Fase 2); `rutas/` y `templates/` solo muestran pantallas.

- Secretos: variables de entorno `NEON_URL`, `SECRET_KEY` y (opcional) `GMAIL_USER`, `GMAIL_APP_PASSWORD`.
- Ejecutar local: `pip install -r requirements.txt` y `python app.py` (ver `.env.example`).
- Publicar: ver `render.yaml` y la guía paso a paso.
- **No suba nunca** archivos `.env` ni cadenas de conexión reales a GitHub.
