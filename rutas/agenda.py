"""Agenda de citas y recordatorios."""
import smtplib
from datetime import time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import base, clinico
from sistema.base import hoy

bp = Blueprint("agenda", __name__)
ESTADOS = {"programada": "Programada", "asistio": "Asistió", "inasistio": "Inasistió",
           "reprogramada": "Reprogramada", "cancelada": "Cancelada"}
MAX_ENVIO_MASIVO = 50


def _hora(texto):
    try:
        return time.fromisoformat(texto) if texto else None
    except ValueError:
        return None


@bp.route("/agenda")
@a.permiso("citas.gestionar")
def citas():
    desde = a.fecha_arg("desde", hoy())
    hasta = a.fecha_arg("hasta", hoy() + timedelta(days=7))
    estado = request.args.get("estado") or None
    medico = a.entero_arg("medico_id")
    ok, filas = a.ejecutar(clinico.listar_citas, a.usuario_actual(), desde, hasta, estado, medico)
    filas = filas if ok else []
    atenciones = {}
    if filas and a.tiene("atenciones.ver"):
        atenciones = {m["cita_id"]: m for m in base.consultar(
            "SELECT id, cita_id, estado FROM atenciones WHERE cita_id = ANY(%s)", ([c["id"] for c in filas],))}
    return render_template("agenda.html", filas=filas, desde=desde, hasta=hasta, estado=estado, medico=medico,
                           estados=ESTADOS, medicos=a.medicos_activos(), atenciones=atenciones)


@bp.route("/agenda/<int:cid>/<accion>", methods=["POST"])
@a.permiso("citas.gestionar")
def accion_cita(cid, accion):
    usuario, f = a.usuario_actual(), request.form
    if accion == "asistencia":
        ok, _ = a.ejecutar(clinico.registrar_asistencia, usuario, cid)
        mensaje = "Asistencia registrada."
    elif accion == "inasistencia":
        ok, _ = a.ejecutar(clinico.marcar_inasistencia, usuario, cid)
        mensaje = "Cita marcada como inasistencia."
    elif accion == "reprogramar":
        ok, _ = a.ejecutar(clinico.reprogramar_cita, usuario, cid, a.fecha_arg("fecha", None), _hora(f.get("hora")),
                           f.get("canal", "correo"))
        mensaje = "Cita reprogramada."
    elif accion == "cancelar":
        ok, _ = a.ejecutar(clinico.cancelar_cita, usuario, cid, f.get("motivo"))
        mensaje = "Cita cancelada."
    else:
        return redirect(url_for("agenda.citas"))
    if ok:
        flash(mensaje, "success")
    return a.volver("agenda.citas")


# ----------------------------------------------------------------------
# Recordatorios
# ----------------------------------------------------------------------
def enviar_uno(usuario, r):
    """Envía el recordatorio por correo y lo marca. Devuelve 'enviado', 'fallido' o 'config'.
    'config' = problema de conexión o de la cuenta de Gmail: el recordatorio NO se marca
    (sigue pendiente) para poder reintentar cuando se corrija la configuración."""
    try:
        a.enviar_correo(r["email"], clinico.mensaje_recordatorio(r))
    except smtplib.SMTPRecipientsRefused:   # el correo del paciente no existe o fue rechazado
        a.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], False)
        return "fallido"
    except Exception as e:
        a.log.warning("Fallo de correo: %s", type(e).__name__)
        return "config:" + type(e).__name__
    ok, _ = a.ejecutar(clinico.marcar_recordatorio, usuario, r["id"], True)
    return "enviado" if ok else "config:BD"


@bp.route("/recordatorios")
@a.permiso("citas.gestionar")
def recordatorios():
    ok, pendientes = a.ejecutar(clinico.recordatorios_pendientes, a.usuario_actual())
    pendientes = pendientes if ok else []
    detalle = [{**r, "mensaje": clinico.mensaje_recordatorio(r)} for r in pendientes[:30]]
    con_correo = sum(1 for r in pendientes if r["email"])
    return render_template("recordatorios.html", total=len(pendientes), detalle=detalle, con_correo=con_correo,
                           lote=min(con_correo, MAX_ENVIO_MASIVO), maximo=MAX_ENVIO_MASIVO,
                           correo=a.correo_configurado())


@bp.route("/recordatorios/<int:rid>/<accion>", methods=["POST"])
@a.permiso("citas.gestionar")
def accion_recordatorio(rid, accion):
    usuario = a.usuario_actual()
    if accion in ("enviado", "fallido"):
        ok, _ = a.ejecutar(clinico.marcar_recordatorio, usuario, rid, accion == "enviado")
        if ok:
            flash("Recordatorio marcado como " + ("enviado." if accion == "enviado" else "fallido."), "success")
    elif accion == "correo":
        ok, pendientes = a.ejecutar(clinico.recordatorios_pendientes, usuario)
        r = next((x for x in (pendientes if ok else []) if x["id"] == rid), None)
        if r is None or not r["email"]:
            flash("El recordatorio no está pendiente o el paciente no tiene correo.", "warning")
        elif not a.correo_configurado():
            flash("El envío por correo no está configurado en el servidor.", "warning")
        else:
            res = enviar_uno(usuario, r)
            if res == "enviado":
                flash("Correo enviado y recordatorio marcado como enviado.", "success")
            elif res == "fallido":
                flash("El destinatario rechazó el correo; se marcó como fallido.", "warning")
            else:
                flash(f"No se pudo enviar: revise la configuración de Gmail ({res.split(':')[1]}).", "danger")
    return redirect(url_for("agenda.recordatorios"))


@bp.route("/recordatorios/masivo", methods=["POST"])
@a.permiso("citas.gestionar")
def envio_masivo():
    usuario = a.usuario_actual()
    if not a.correo_configurado():
        flash("El envío por correo no está configurado en el servidor.", "warning")
        return redirect(url_for("agenda.recordatorios"))
    ok, pendientes = a.ejecutar(clinico.recordatorios_pendientes, usuario)
    lote = [r for r in (pendientes if ok else []) if r["email"]][:MAX_ENVIO_MASIVO]
    conteo, error = {"enviado": 0, "fallido": 0}, None
    for r in lote:
        res = enviar_uno(usuario, r)
        if res.startswith("config"):   # no seguir insistiendo si Gmail rechaza la cuenta
            error = res.split(":")[1]
            break
        conteo[res] += 1
    flash(f"Enviados: {conteo['enviado']} · Rechazados por el destinatario: {conteo['fallido']}",
          "success" if not error else "warning")
    if error:
        flash(f"Se detuvo el envío: no se pudo conectar con Gmail o la cuenta fue rechazada ({error}). "
              "Revise GMAIL_USER y GMAIL_APP_PASSWORD.", "danger")
    return redirect(url_for("agenda.recordatorios"))
