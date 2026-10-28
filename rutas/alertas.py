"""Alertas de seguimiento: controles vencidos y pacientes inasistentes."""
from flask import Blueprint, render_template

import ayudas as a
from sistema import clinico

bp = Blueprint("alertas", __name__)

COL_VENCIDOS = ["codigo", "paciente", "telefono", "diagnostico_cie10", "fecha_ultimo_control", "dias_vencido"]
COL_INASIST = ["codigo", "paciente", "telefono", "inasistencias", "ultima_inasistencia"]
NOMBRES = {"codigo": "Código", "paciente": "Paciente", "telefono": "Teléfono", "inasistencias": "Inasistencias",
           "ultima_inasistencia": "Última inasistencia", "diagnostico_cie10": "Diagnóstico",
           "fecha_ultimo_control": "Último control", "dias_vencido": "Días de atraso"}


@bp.route("/alertas")
@a.permiso("pacientes.ver")
def vencidos():
    ok, filas = a.ejecutar(clinico.alertas_seguimiento, a.usuario_actual())
    filas = filas if ok else []
    columnas = [c for c in (filas[0].keys() if filas else []) if c not in ("caso_id",)]
    return render_template("alertas_vencidos.html", filas=filas, columnas=columnas, nombres=NOMBRES)


@bp.route("/alertas/inasistentes")
@a.permiso("pacientes.ver")
def inasistentes():
    dias = max(7, min(180, a.entero_arg("dias", 60)))
    ok, filas = a.ejecutar(clinico.pacientes_inasistentes, a.usuario_actual(), dias)
    return render_template("alertas_inasistentes.html", filas=filas if ok else [], dias=dias)


@bp.route("/alertas/vencidos.csv")
@a.permiso("pacientes.ver")
def csv_vencidos():
    ok, filas = a.ejecutar(clinico.alertas_seguimiento, a.usuario_actual())
    columnas = [c for c in (filas[0].keys() if ok and filas else []) if c != "caso_id"]
    return a.descargar_csv(filas if ok else [], columnas, NOMBRES, "controles_vencidos.csv")


@bp.route("/alertas/inasistentes.csv")
@a.permiso("pacientes.ver")
def csv_inasistentes():
    ok, filas = a.ejecutar(clinico.pacientes_inasistentes, a.usuario_actual(), max(7, min(180, a.entero_arg("dias", 60))))
    return a.descargar_csv(filas if ok else [], COL_INASIST, NOMBRES, "pacientes_inasistentes.csv")
