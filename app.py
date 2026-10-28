"""Aplicación web (Flask) del sistema de control de pacientes de Gastroenterología.
Hospital Nacional Arzobispo Loayza, Lima - Perú, 2026.

QUÉ HACE ESTE ARCHIVO
  Crea la aplicación, define el menú según el rol, protege los formularios (CSRF),
  controla la inactividad de la sesión y registra las pantallas (carpeta `rutas/`).
  La lógica clínica, los permisos, la auditoría y los indicadores están en `sistema/` (Fase 2).

CONEXIÓN A NEON
  La cadena de conexión NO está en el código: se lee de la variable de entorno NEON_URL
  (en Render: Environment). También se acepta DATABASE_URL.

EJECUCIÓN LOCAL (prueba)
  pip install -r requirements.txt
  NEON_URL="postgresql://..." python app.py        (en Windows PowerShell: $env:NEON_URL="...")
EJECUCIÓN EN RENDER
  gunicorn app:app   (ver render.yaml)
"""
import logging
import os
import secrets
from datetime import timedelta

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape

import ayudas as a
from sistema import base

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Menú lateral: (pantalla, texto, ícono, permisos que la habilitan: basta con tener uno)
MENU = [
    ("inicio.inicio", "Inicio", "bi-speedometer2", None),
    ("pacientes.buscar", "Pacientes", "bi-people", ["pacientes.ver"]),
    ("agenda.citas", "Agenda", "bi-calendar-check", ["citas.gestionar"]),
    ("agenda.recordatorios", "Recordatorios", "bi-envelope-paper", ["citas.gestionar"]),
    ("atencion.lista", "Atención clínica", "bi-heart-pulse", ["atenciones.ver"]),
    ("alertas.vencidos", "Alertas de seguimiento", "bi-bell", ["pacientes.ver"]),
    ("indicadores.panel", "Indicadores y reportes", "bi-bar-chart-line", ["reportes.ver"]),
    ("admin.usuarios", "Administración", "bi-shield-lock", ["usuarios.administrar", "auditoria.ver"]),
    ("cuenta.cuenta", "Mi cuenta", "bi-person-circle", None),
]
ROLES = {"medico": "Médico", "enfermeria": "Enfermería", "administrativo": "Administrativo",
         "administrador": "Administrador"}


def crear_app():
    app = Flask(__name__)
    en_render = bool(os.environ.get("RENDER"))
    clave = os.environ.get("SECRET_KEY")
    if not clave:
        clave = secrets.token_hex(32)   # sin SECRET_KEY las sesiones se pierden al reiniciar
        logging.getLogger("gastro").warning("Falta SECRET_KEY: se usa una clave temporal.")
    app.config.update(
        SECRET_KEY=clave,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=en_render,          # en Render todo va por HTTPS
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=1024 * 1024,
        JSON_AS_ASCII=False,
    )
    os.environ.setdefault("PGCONNECT_TIMEOUT", "20")   # evita esperas infinitas si Neon está dormida
    # La app lee NEON_URL; si solo existe DATABASE_URL (nombre usado antes) se copia
    if not os.environ.get("NEON_URL") and os.environ.get("DATABASE_URL"):
        os.environ["NEON_URL"] = os.environ["DATABASE_URL"]

    # --- Pantallas ---
    from rutas import admin, agenda, alertas, atencion, auth, cuenta, indicadores, inicio, pacientes
    for modulo in (auth, inicio, pacientes, agenda, atencion, alertas, indicadores, admin, cuenta):
        app.register_blueprint(modulo.bp)

    # --- Filtros de formato para las plantillas ---
    app.add_template_filter(a.fecha_txt, "fecha")
    app.add_template_filter(a.hora_txt, "hora")
    app.add_template_filter(a.fechahora_txt, "fechahora")
    app.add_template_filter(a.humano, "humano")

    # --- Antes de cada petición ---
    @app.before_request
    def antes():
        if request.endpoint in (None, "static", "salud"):
            return None
        if a.controlar_inactividad():
            return redirect(url_for("auth.login"))
        session.permanent = True
        if request.method == "POST":
            a.verificar_csrf()
        return None

    # --- Después de cada respuesta ---
    @app.after_request
    def despues(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"   # nunca guardar datos clínicos en el navegador
        return resp

    # --- Campo oculto con el código anti-CSRF para los formularios: {{ csrf() }} ---
    app.add_template_global(lambda: Markup(f'<input type="hidden" name="_csrf" value="{escape(a.token_csrf())}">'), "csrf")

    def es_activo(endpoint):
        """¿La pantalla actual pertenece a esta opción del menú?"""
        actual, bloque = request.endpoint or "", endpoint.split(".")[0]
        if bloque == "agenda":
            recordatorios = actual in ("agenda.recordatorios", "agenda.accion_recordatorio", "agenda.envio_masivo")
            return recordatorios if endpoint == "agenda.recordatorios" else (actual.startswith("agenda.") and not recordatorios)
        return actual.split(".")[0] == bloque

    # --- Datos disponibles en todas las plantillas ---
    @app.context_processor
    def contexto():
        usuario = a.usuario_actual()
        menu = [m for m in MENU if m[3] is None or any(a.tiene(p) for p in m[3])] if usuario else []
        return {"usuario": usuario, "menu": menu, "es_activo": es_activo, "tiene": a.tiene,
                "rol_txt": lambda r: ROLES.get(r, str(r).capitalize()), "hoy": base.hoy(),
                "datos_simulados": a.hay_datos_simulados() if usuario else False,
                "ahora_txt": lambda: a.fechahora_txt(base.ahora())}

    # --- Salud (Render la consulta para saber si la app está viva; no usa la base) ---
    @app.route("/salud")
    def salud():
        return {"estado": "ok"}

    # --- Páginas de error ---
    def pagina_error(codigo, titulo, detalle):
        return render_template("error.html", codigo=codigo, titulo=titulo, detalle=detalle), codigo

    @app.errorhandler(400)
    def e400(e):
        return pagina_error(400, "Solicitud no válida", getattr(e, "description", "") or "Recargue la página e intente de nuevo.")

    @app.errorhandler(403)
    def e403(e):
        return pagina_error(403, "Sin permiso", "Su rol no tiene acceso a esta pantalla.")

    @app.errorhandler(404)
    def e404(e):
        return pagina_error(404, "No encontrada", "La página que busca no existe.")

    @app.errorhandler(500)
    def e500(e):
        return pagina_error(500, "Error inesperado", "Avise al administrador del sistema.")

    return app


app = crear_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("DEPURAR")))
