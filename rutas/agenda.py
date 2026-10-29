"""Agenda de citas y recordatorios."""
import re
import unicodedata
from urllib.parse import quote
from datetime import time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import base, clinico
from sistema.base import hoy

bp = Blueprint("agenda", __name__)
ESTADOS = {"programada": "Programada", "asistio": "Asistió", "inasistio": "Inasistió",
           "reprogramada": "Reprogramada", "cancelada": "Cancelada"}


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


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
                           "whatsapp")
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
def numero_whatsapp(telefono):
    """Teléfono → número internacional solo con dígitos (Perú: 9 dígitos → 51 + número). None si no sirve."""
    d = re.sub(r"\D", "", telefono or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 9:
        d = "51" + d
    return d if 10 <= len(d) <= 15 else None


def enlace_whatsapp(telefono, mensaje):
    """Enlace que abre WhatsApp Web (en la pestaña ya abierta) con el chat y el mensaje escritos."""
    num = numero_whatsapp(telefono)
    return f"https://web.whatsapp.com/send?phone={num}&text={quote(mensaje)}" if num else None


@bp.route("/recordatorios")
@a.permiso("citas.gestionar")
def recordatorios():
    ok, pendientes = a.ejecutar(clinico.recordatorios_pendientes, a.usuario_actual())
    pendientes = pendientes if ok else []
    q = (request.args.get("q") or "").strip()
    visibles = list(reversed(pendientes))   # los más recientes primero
    if q:   # buscador: por nombre (sin distinguir tildes ni mayúsculas) o por teléfono
        visibles = [r for r in visibles if all(
            _sin_tildes(p) in _sin_tildes(f"{r['paciente']} {r['telefono'] or ''}") for p in q.split())]
    detalle = []
    for r in visibles[:30]:
        mensaje = clinico.mensaje_recordatorio(r)
        detalle.append({**r, "mensaje": mensaje, "wa": enlace_whatsapp(r["telefono"], mensaje)})
    con_telefono = sum(1 for r in pendientes if numero_whatsapp(r["telefono"]))
    return render_template("recordatorios.html", total=len(pendientes), detalle=detalle,
                           con_telefono=con_telefono, q=q, encontrados=len(visibles))


@bp.route("/recordatorios/<int:rid>/<accion>", methods=["POST"])
@a.permiso("citas.gestionar")
def accion_recordatorio(rid, accion):
    usuario = a.usuario_actual()
    if accion in ("enviado", "fallido"):
        ok, _ = a.ejecutar(clinico.marcar_recordatorio, usuario, rid, accion == "enviado")
        if ok:
            flash("Recordatorio marcado como " + ("enviado." if accion == "enviado" else "fallido."), "success")
    return redirect(url_for("agenda.recordatorios"))
