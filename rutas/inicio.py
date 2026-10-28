"""Inicio: panel resumen del día según los permisos del usuario."""
from datetime import date, timedelta

from flask import Blueprint, render_template

import ayudas as a
from rutas import indicadores as ind
from sistema import clinico, reportes
from sistema.base import hoy

bp = Blueprint("inicio", __name__)

FUNCIONES = {
    "pacientes.ver": "Buscar pacientes y ver sus fichas y alertas de seguimiento",
    "pacientes.editar": "Registrar pacientes y abrir sus casos de control",
    "citas.gestionar": "Programar, reprogramar y cancelar citas; registrar asistencia; enviar recordatorios",
    "atenciones.ver": "Consultar atenciones clínicas e historiales",
    "atenciones.registrar": "Registrar atenciones con la lista de verificación del protocolo",
    "eventos.registrar": "Registrar eventos adversos",
    "reportes.ver": "Ver indicadores y descargar reportes en Excel",
    "auditoria.ver": "Consultar la bitácora de auditoría y los accesos al sistema",
    "usuarios.administrar": "Crear y administrar usuarios",
}
ESTADOS = ["asistio", "programada", "inasistio", "reprogramada", "cancelada"]


@bp.route("/")
@a.login_requerido
def inicio():
    usuario = a.usuario_actual()
    tarjetas, citas_14d = [], []
    if a.tiene("citas.gestionar"):
        ok, citas_14d = a.ejecutar(clinico.listar_citas, usuario, hoy() - timedelta(days=13), hoy())
        citas_14d = citas_14d if ok else []
        if ok:
            de_hoy = [c for c in citas_14d if c["fecha_programada"] == hoy() and c["estado"] in ("programada", "asistio")]
            tarjetas.append({"titulo": "Citas de hoy", "valor": len(de_hoy), "color": "azul", "icono": "bi-calendar-check",
                             "detalle": f"{sum(c['estado'] == 'asistio' for c in de_hoy)} ya asistieron",
                             "enlace": "agenda.citas"})
        ok, pendientes = a.ejecutar(clinico.recordatorios_pendientes, usuario)
        if ok:
            tarjetas.append({"titulo": "Recordatorios por enviar", "valor": len(pendientes), "color": "ambar",
                             "icono": "bi-envelope-paper", "detalle": "cuya hora de envío ya llegó",
                             "enlace": "agenda.recordatorios"})
    vencidos = []
    if a.tiene("pacientes.ver"):
        ok, vencidos = a.ejecutar(clinico.alertas_seguimiento, usuario)
        vencidos = vencidos if ok else []
        if ok:
            tarjetas.append({"titulo": "Controles vencidos", "valor": len(vencidos), "color": "rojo", "icono": "bi-bell",
                             "detalle": "pacientes que superaron su plazo", "enlace": "alertas.vencidos"})

    # Gráfico: citas de los últimos 14 días por estado
    grafico = None
    if citas_14d:
        dias = [hoy() - timedelta(days=i) for i in range(13, -1, -1)]
        grafico = {"dias": [d.strftime("%d/%m") for d in dias],
                   "series": [{"estado": e, "valores": [sum(1 for c in citas_14d if c["estado"] == e and c["fecha_programada"] == d)
                                                        for d in dias]} for e in ESTADOS]}
        grafico["series"] = [s for s in grafico["series"] if any(s["valores"])]

    modulos = []
    if a.tiene("reportes.ver"):
        ok, tabla = a.ejecutar(reportes.indicadores, usuario, date(hoy().year, 1, 1), hoy())
        if ok:
            modulos = [{"titulo": titulo, "icono": icono, "tarjetas": ind.tarjetas(tabla, clave)}
                       for clave, titulo, icono in ind.MODULOS]
    return render_template("inicio.html", tarjetas=tarjetas, grafico=grafico, modulos=modulos,
                           vencidos=vencidos[:8], total_vencidos=len(vencidos),
                           funciones=[FUNCIONES.get(p, p) for p in sorted(usuario["permisos"])])
