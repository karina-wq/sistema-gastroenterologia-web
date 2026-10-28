"""Ayudas compartidas por todas las pantallas de la aplicación web.

Aquí vive lo que se repite en varias pantallas:
  - la sesión (quién entró, cierre por inactividad) y la protección contra CSRF,
  - los permisos por pantalla,
  - ejecutar funciones del paquete `sistema` mostrando sus errores en español,
  - catálogos pequeños guardados unos minutos (médicos, diagnósticos, roles),
  - formato de fechas/horas, descargas CSV y envío de correos.

TODA la lógica de negocio (permisos, validaciones, auditoría, indicadores) sigue en el
paquete `sistema/` de la Fase 2: este archivo y las rutas solo conectan la web con él.
"""
import csv
import io
import ipaddress
import logging
import os
import secrets
import smtplib
import ssl
import time
from datetime import date, datetime
from email.message import EmailMessage
from functools import wraps

import psycopg2
from flask import Response, abort, flash, g, redirect, request, session, url_for

from sistema import base
from sistema.base import ErrorValidacion, NoEncontrado, PermisoDenegado

log = logging.getLogger("gastro")
SESION_MINUTOS = 30   # tras este tiempo sin actividad se cierra la sesión


# ----------------------------------------------------------------------
# 1. Sesión y CSRF
# ----------------------------------------------------------------------
def usuario_actual():
    """Datos del usuario con sesión iniciada (o None). Se arma una vez por petición."""
    if "usuario" not in g:
        g.usuario = session.get("usuario")
    return g.usuario


def tiene(permiso):
    return base.tiene_permiso(usuario_actual(), permiso)


def token_csrf():
    """Código secreto que acompaña a cada formulario para impedir envíos desde otros sitios."""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


def verificar_csrf():
    esperado = session.get("_csrf")
    recibido = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
    if not esperado or not recibido or not secrets.compare_digest(esperado, recibido):
        abort(400, "La página expiró. Recargue e intente de nuevo.")


def controlar_inactividad():
    """Cierra la sesión si pasaron SESION_MINUTOS sin usar la aplicación. Devuelve True si la cerró."""
    if "usuario" not in session:
        return False
    ahora = time.time()
    if ahora - session.get("_ultima", ahora) > SESION_MINUTOS * 60:
        session.clear()
        flash(f"La sesión se cerró por inactividad ({SESION_MINUTOS} minutos).", "info")
        return True
    session["_ultima"] = ahora
    return False


def ip_y_agente():
    """IP y navegador de quien inicia sesión (para la bitácora de accesos). Nunca rompe el inicio."""
    agente = (request.headers.get("User-Agent") or "")[:250] or None
    try:
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        ipaddress.ip_address(ip)   # valida el formato (la columna es de tipo inet)
        return ip, agente
    except ValueError:
        return None, agente


# ----------------------------------------------------------------------
# 2. Permisos por pantalla
# ----------------------------------------------------------------------
def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if usuario_actual() is None:
            return redirect(url_for("auth.login", siguiente=request.full_path if request.method == "GET" else None))
        return vista(*args, **kwargs)
    return envoltura


def permiso(*permisos):
    """Exige iniciar sesión y tener al menos uno de los permisos indicados."""
    def decorador(vista):
        @wraps(vista)
        @login_requerido
        def envoltura(*args, **kwargs):
            if not any(tiene(p) for p in permisos):
                try:   # el intento queda en la bitácora de accesos (indicador de seguridad)
                    base._registrar_denegado(usuario_actual(), permisos[0])
                except Exception:
                    log.exception("No se pudo registrar el acceso denegado")
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


# ----------------------------------------------------------------------
# 3. Ejecutar funciones del paquete `sistema`
# ----------------------------------------------------------------------
def ejecutar(funcion, *args, **kwargs):
    """Ejecuta una función del paquete. Devuelve (True, resultado) o (False, None);
    si falla, el mensaje en español ya quedó en pantalla (flash)."""
    try:
        return True, funcion(*args, **kwargs)
    except (ErrorValidacion, NoEncontrado, PermisoDenegado) as e:
        flash(str(e), "warning")
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        log.exception("Sin conexión con la base de datos")
        flash("No se pudo conectar con la base de datos. Espere unos segundos y vuelva a intentar "
              "(si estaba inactiva, tarda un momento en despertar).", "danger")
    except Exception as e:   # error inesperado: no se muestran detalles técnicos al personal
        log.exception("Error inesperado")
        flash("Ocurrió un error inesperado. Avise al administrador del sistema.", "danger")
        if os.environ.get("DEPURAR", "").lower() in ("1", "true", "si"):
            flash(f"{type(e).__name__}: {e}", "danger")
    return False, None


def volver(defecto="inicio.inicio"):
    """Redirige a la pantalla de origen (campo oculto «volver») o a una por defecto."""
    destino = request.form.get("volver") or request.args.get("volver")
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return redirect(destino)
    return redirect(url_for(defecto))


# ----------------------------------------------------------------------
# 4. Catálogos pequeños (se guardan 5 minutos)
# ----------------------------------------------------------------------
_cache = {}


def _con_cache(clave, segundos, calcular):
    ahora = time.time()
    vencimiento, valor = _cache.get(clave, (0, None))
    if ahora < vencimiento:
        return valor
    valor = calcular()
    _cache[clave] = (ahora + segundos, valor)
    return valor


def olvidar_catalogos():
    _cache.clear()


def medicos_activos():
    """{id: 'Nombre Apellido'} de los médicos activos."""
    def calcular():
        filas = base.consultar("""SELECT u.id, u.nombres || ' ' || u.apellidos AS nombre
                                  FROM usuarios u JOIN roles r ON r.id = u.rol_id
                                  WHERE r.nombre = 'medico' AND u.activo ORDER BY u.apellidos, u.nombres""")
        return {f["id"]: f["nombre"] for f in filas}
    return _con_cache("medicos", 300, calcular)


def diagnosticos():
    """{código CIE-10: 'K29.7 · descripción'}."""
    def calcular():
        filas = base.consultar("SELECT codigo, descripcion FROM cie10 ORDER BY codigo")
        return {f["codigo"]: f"{f['codigo']} · {f['descripcion']}" for f in filas}
    return _con_cache("diagnosticos", 300, calcular)


def roles_disponibles():
    return _con_cache("roles", 300, lambda: [f["nombre"] for f in base.consultar("SELECT nombre FROM roles ORDER BY id")])


def hay_datos_simulados():
    """True si la base todavía tiene pacientes de prueba (código SIM-...)."""
    def calcular():
        try:
            return base.consultar("SELECT count(*) AS n FROM pacientes WHERE codigo LIKE 'SIM-%'")[0]["n"] > 0
        except Exception:
            return False
    return _con_cache("simulados", 120, calcular)


# ----------------------------------------------------------------------
# 5. Formato
# ----------------------------------------------------------------------
def fecha_txt(valor):
    if not valor:
        return "—"
    if isinstance(valor, datetime) and valor.tzinfo:
        valor = valor.astimezone(base.TZ)
    return valor.strftime("%d/%m/%Y")


def hora_txt(valor):
    if not valor:
        return "—"
    if isinstance(valor, datetime) and valor.tzinfo:
        valor = valor.astimezone(base.TZ)
    return valor.strftime("%H:%M")


def fechahora_txt(valor):
    if not valor:
        return "—"
    return f"{fecha_txt(valor)} {hora_txt(valor)}"


CAMPOS_LEGIBLES = {"motivo_consulta": "motivo de consulta", "anamnesis": "anamnesis", "examen_fisico": "examen físico",
                   "diagnostico_cie10": "diagnóstico (CIE-10)", "tratamiento": "tratamiento", "indicaciones": "indicaciones",
                   "observaciones": "observaciones", "hora_llegada": "hora de llegada"}


def humano(campo):
    """Nombre de un campo de la base en palabras (motivo_consulta → motivo de consulta)."""
    return CAMPOS_LEGIBLES.get(campo, str(campo).replace("_", " "))


def fecha_arg(nombre, defecto):
    """Fecha de la URL (?desde=2026-10-01) o la de por defecto si falta o es inválida."""
    texto = request.values.get(nombre)
    try:
        return date.fromisoformat(texto) if texto else defecto
    except ValueError:
        return defecto


def entero_arg(nombre, defecto=None):
    try:
        return int(request.values.get(nombre))
    except (TypeError, ValueError):
        return defecto


def registros(df):
    """DataFrame → lista de diccionarios con NaN convertidos en None."""
    if df is None or df.empty:
        return []
    return df.astype(object).where(df.notna(), None).to_dict("records")


def descargar_csv(filas, columnas, nombres, archivo):
    """Respuesta CSV (con BOM para que Excel respete las tildes)."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow([nombres.get(c, c) for c in columnas])
    for fila in filas:
        escritor.writerow(["" if fila.get(c) is None else _texto_csv(fila.get(c)) for c in columnas])
    return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


def _texto_csv(valor):
    if isinstance(valor, datetime):
        return fechahora_txt(valor)
    if isinstance(valor, date):
        return fecha_txt(valor)
    if isinstance(valor, (list, tuple, set)):
        return ", ".join(map(str, valor))
    return str(valor)


# ----------------------------------------------------------------------
# 6. Correo (recordatorios por Gmail)
# ----------------------------------------------------------------------
ASUNTO = "Recordatorio de control - Gastroenterología, Hospital Nacional Arzobispo Loayza"


def correo_configurado():
    return bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))


def enviar_correo(destino, cuerpo, asunto=ASUNTO):
    """Envía un correo de texto simple. Lanza una excepción si Gmail lo rechaza."""
    usuario = os.environ["GMAIL_USER"].strip()
    clave = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")   # Gmail la muestra con espacios
    mensaje = EmailMessage()
    mensaje["From"] = f"Gastroenterología HNAL <{usuario}>"
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as servidor:
        servidor.login(usuario, clave)
        servidor.send_message(mensaje)
