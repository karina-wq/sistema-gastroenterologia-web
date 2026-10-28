"""Pacientes: búsqueda, registro, ficha, casos de control y programación de citas."""
from datetime import date, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import clinico
from sistema.base import hoy

bp = Blueprint("pacientes", __name__)

NIVELES = ["", "Sin instrucción", "Primaria", "Secundaria", "Técnico", "Superior universitario", "Posgrado"]
CAMPOS = ["nombres", "apellidos", "fecha_nacimiento", "sexo", "dni", "telefono", "email", "direccion",
          "nivel_educativo", "contacto_emergencia"]


def _datos_formulario():
    return {c: (request.form.get(c) or "").strip() for c in CAMPOS}


def _hora(texto, defecto=time(9, 0)):
    try:
        return time.fromisoformat(texto) if texto else defecto
    except ValueError:
        return defecto


@bp.route("/pacientes")
@a.permiso("pacientes.ver")
def buscar():
    q = (request.args.get("q") or "").strip()
    filas = None
    if q:
        ok, filas = a.ejecutar(clinico.buscar_pacientes, a.usuario_actual(), q)
        filas = filas if ok else []
    return render_template("pacientes_buscar.html", q=q, filas=filas)


@bp.route("/pacientes/nuevo", methods=["GET", "POST"])
@a.permiso("pacientes.editar")
def nuevo():
    datos = _datos_formulario() if request.method == "POST" else {}
    if request.method == "POST":
        ok, r = a.ejecutar(clinico.registrar_paciente, a.usuario_actual(), datos)
        if ok:
            flash(f"Paciente registrado con el código {r['codigo']}.", "success")
            return redirect(url_for("pacientes.ficha", pid=r["id"]))
    return render_template("paciente_nuevo.html", datos=datos, niveles=NIVELES)


@bp.route("/pacientes/<int:pid>")
@a.permiso("pacientes.ver")
def ficha(pid):
    usuario = a.usuario_actual()
    ok, p = a.ejecutar(clinico.obtener_paciente, usuario, pid)
    if not ok:
        return redirect(url_for("pacientes.buscar"))
    caso_activo = next((c for c in p["casos"] if c["estado"] == "en_seguimiento"), None)
    historial = []
    if a.tiene("atenciones.ver"):
        ok, historial = a.ejecutar(clinico.historial_paciente, usuario, pid)
        historial = historial if ok else []
    proximas = []
    if a.tiene("citas.gestionar"):
        ok, citas = a.ejecutar(clinico.listar_citas, usuario, hoy() - timedelta(days=60), hoy() + timedelta(days=365), None, None, 2000)
        proximas = [c for c in (citas if ok else []) if c["paciente_id"] == pid][-8:]
    edad = None
    if p.get("fecha_nacimiento"):
        n, h = p["fecha_nacimiento"], hoy()
        edad = h.year - n.year - ((h.month, h.day) < (n.month, n.day))
    return render_template("paciente_ficha.html", p=p, edad=edad, caso_activo=caso_activo, historial=historial,
                           citas=proximas, niveles=NIVELES, medicos=a.medicos_activos(), diagnosticos=a.diagnosticos())


@bp.route("/pacientes/<int:pid>/editar", methods=["POST"])
@a.permiso("pacientes.editar")
def editar(pid):
    ok, _ = a.ejecutar(clinico.actualizar_paciente, a.usuario_actual(), pid, _datos_formulario())
    if ok:
        flash("Datos del paciente actualizados.", "success")
    return redirect(url_for("pacientes.ficha", pid=pid))


@bp.route("/pacientes/<int:pid>/caso", methods=["POST"])
@a.permiso("pacientes.editar")
def abrir_caso(pid):
    f = request.form
    medico = a.entero_arg("medico_id")
    plazo = a.entero_arg("plazo", 0) or None
    ok, _ = a.ejecutar(clinico.abrir_caso, a.usuario_actual(), pid, f.get("diagnostico"), medico,
                       a.entero_arg("frecuencia", 30), plazo, None, f.get("observaciones"))
    if ok:
        flash("Caso de control abierto.", "success")
    return redirect(url_for("pacientes.ficha", pid=pid))


@bp.route("/pacientes/<int:pid>/cita", methods=["POST"])
@a.permiso("citas.gestionar")
def programar_cita(pid):
    f = request.form
    usuario = a.usuario_actual()
    caso_id = a.entero_arg("caso_id")
    fecha = a.fecha_arg("fecha", None)
    canal = f.get("canal", "correo")
    ok, _ = a.ejecutar(clinico.programar_cita, usuario, caso_id, fecha, _hora(f.get("hora")),
                       a.entero_arg("medico_id"), f.get("motivo") or "Control programado", canal)
    if ok:
        flash("Cita programada. Se generó su recordatorio (2 días antes, 9:00 a. m.).", "success")
        if canal == "correo" and not (f.get("email_paciente") or "").strip():
            flash("Este paciente no tiene correo registrado: agréguelo en «Editar datos» para que el "
                  "recordatorio pueda enviarse.", "warning")
    return redirect(url_for("pacientes.ficha", pid=pid))


@bp.route("/pacientes/<int:pid>/cerrar-caso", methods=["POST"])
@a.permiso("atenciones.registrar")
def cerrar_caso(pid):
    f = request.form
    ok, canceladas = a.ejecutar(clinico.cerrar_caso, a.usuario_actual(), a.entero_arg("caso_id"),
                                f.get("estado"), None, f.get("observaciones"))
    if ok:
        flash(f"Caso cerrado. Citas futuras canceladas: {canceladas}.", "success")
    return redirect(url_for("pacientes.ficha", pid=pid))
