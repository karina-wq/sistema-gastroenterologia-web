"""Indicadores y reportes: los 6 indicadores de la tesis agrupados en sus 3 módulos
(Seguimiento de control, Calidad del control y Seguridad), con detalle y descarga a Excel."""
import os
import tempfile
from datetime import date, timedelta

import pandas as pd
from flask import Blueprint, after_this_request, render_template, request, send_file

import ayudas as a
from sistema import reportes, seguridad
from sistema.base import hoy

bp = Blueprint("indicadores", __name__)

# código del indicador → (módulo, nombre, fórmula, ¿un valor más alto es mejor?)
INDICADORES = {
    "SEGUI_CUMPLIMIENTO": ("Seguimiento", "Cumplimiento de controles",
                           "Controles asistidos ÷ controles programados", True),
    "SEGUI_ACTUALIZADO": ("Seguimiento", "Seguimiento actualizado",
                          "Pacientes activos con control dentro del plazo ÷ pacientes activos", True),
    "CALID_PROTOCOLOS": ("Calidad", "Cumplimiento del protocolo",
                         "Atenciones con todos los pasos del protocolo ÷ atenciones", True),
    "CALID_COMPLETOS": ("Calidad", "Registros completos",
                        "Registros con todos los campos obligatorios ÷ registros", True),
    "SEGUR_EVENTOS": ("Seguridad", "Eventos adversos",
                      "Atenciones con evento adverso ÷ atenciones", False),
    "SEGUR_ACCESOS": ("Seguridad", "Accesos no autorizados",
                      "Intentos de acceso no exitosos ÷ intentos de acceso totales", False),
}
MODULOS = [("Seguimiento", "Seguimiento de control", "bi-arrow-repeat"),
           ("Calidad", "Calidad del control", "bi-clipboard2-check"),
           ("Seguridad", "Seguridad", "bi-shield-check")]
PREFIJO = {"Seguimiento": "SEGUI_", "Calidad": "CALID_", "Seguridad": "SEGUR_"}


def col_codigo(df):
    """Nombre de la columna que contiene los códigos de indicador."""
    for c in df.columns:
        if df[c].astype(str).isin(list(INDICADORES)).any():
            return c
    return None


def _entero(v):
    return None if v is None or pd.isna(v) else int(v)


def tarjetas(ind, modulo):
    """Lista de tarjetas (una por indicador) del módulo, lista para la plantilla."""
    col = col_codigo(ind) if ind is not None and not ind.empty else None
    salida = []
    for codigo, (mod, nombre, formula, mayor) in INDICADORES.items():
        if mod != modulo:
            continue
        fila = ind[ind[col].astype(str) == codigo] if col else None
        t = {"codigo": codigo, "nombre": nombre, "formula": formula, "mayor_mejor": mayor,
             "porcentaje": None, "numerador": None, "denominador": None}
        if fila is not None and not fila.empty:
            r = fila.iloc[0]
            pct = r.get("porcentaje")
            t["porcentaje"] = None if pct is None or pd.isna(pct) else round(float(pct), 1)
            t["numerador"], t["denominador"] = _entero(r.get("numerador")), _entero(r.get("denominador"))
        salida.append(t)
    return salida


def serie_mensual(mens, modulo, desde, hasta):
    """Datos del gráfico de evolución mensual: {'meses': [...], 'series': [{'nombre', 'valores'}]}."""
    col = col_codigo(mens) if mens is not None and not mens.empty else None
    if not col:
        return None
    sub = mens[mens[col].astype(str).str.startswith(PREFIJO[modulo])].copy()
    sub["mes"] = pd.to_datetime(sub["mes"])
    sub = sub[(sub["mes"] >= pd.Timestamp(desde.replace(day=1))) & (sub["mes"] <= pd.Timestamp(hasta))]
    if sub.empty:
        return None
    sub["indicador"] = sub[col].map(lambda c: INDICADORES[c][1] if c in INDICADORES else c)
    tabla = sub.pivot_table(index="mes", columns="indicador", values="porcentaje", aggfunc="first").sort_index()
    return {"meses": [m.strftime("%m/%Y") for m in tabla.index],
            "series": [{"nombre": c, "valores": [None if pd.isna(v) else round(float(v), 1) for v in tabla[c]]}
                       for c in tabla.columns]}


@bp.route("/indicadores")
@a.permiso("reportes.ver")
def panel():
    usuario = a.usuario_actual()
    desde = a.fecha_arg("desde", date(hoy().year, 1, 1))
    hasta = a.fecha_arg("hasta", hoy())
    if desde > hasta:
        a.flash("La fecha «Desde» no puede ser posterior a «Hasta».", "warning")
        desde, hasta = date(hoy().year, 1, 1), hoy()
    consultas = {"indicadores": (reportes.indicadores, usuario, desde, hasta),
                 "mensual": (reportes.indicadores_mensuales, usuario),
                 "tiempos": (reportes.tiempos_atencion, usuario, desde, hasta),
                 "satisfaccion": (reportes.satisfaccion, usuario, desde, hasta),
                 "citas": (reportes.citas_por_estado, usuario, desde, hasta),
                 "incompletos": (reportes.registros_incompletos, usuario, desde, hasta),
                 "eventos": (reportes.eventos_adversos_detalle, usuario, desde, hasta)}
    datos = {}
    for nombre, (funcion, *args) in consultas.items():
        ok, valor = a.ejecutar(funcion, *args)
        if not ok:
            return render_template("indicadores.html", desde=desde, hasta=hasta, error=True)
        datos[nombre] = valor

    modulos = []
    for clave, titulo, icono in MODULOS:
        modulos.append({"clave": clave, "titulo": titulo, "icono": icono,
                        "tarjetas": tarjetas(datos["indicadores"], clave),
                        "grafico": serie_mensual(datos["mensual"], clave, desde, hasta)})
    t, s = datos["tiempos"], datos["satisfaccion"]
    accesos = []
    if a.tiene("auditoria.ver"):
        ok, accesos = a.ejecutar(seguridad.consultar_accesos, usuario, desde, hasta, True, 200)
        accesos = accesos if ok else []
    return render_template(
        "indicadores.html", desde=desde, hasta=hasta, error=False, modulos=modulos,
        citas=a.registros(datos["citas"]), tiempos=(a.registros(t) or [None])[0],
        satisfaccion=(a.registros(s) or [None])[0], incompletos=a.registros(datos["incompletos"]),
        eventos=a.registros(datos["eventos"]), accesos=accesos)


@bp.route("/indicadores/excel")
@a.permiso("reportes.ver")
def excel():
    """Genera el Excel de 8 hojas con el paquete (queda registrado en la bitácora) y lo descarga."""
    desde = a.fecha_arg("desde", date(hoy().year, 1, 1))
    hasta = a.fecha_arg("hasta", hoy())
    carpeta = tempfile.mkdtemp()
    ruta = os.path.join(carpeta, "reporte_indicadores.xlsx")
    ok, _ = a.ejecutar(reportes.exportar_excel, a.usuario_actual(), desde, hasta, ruta)
    if not ok:
        return a.volver("indicadores.panel")

    @after_this_request
    def limpiar(resp):
        try:
            os.remove(ruta)
            os.rmdir(carpeta)
        except OSError:
            pass
        return resp
    return send_file(ruta, as_attachment=True, download_name=f"reporte_indicadores_{desde}_{hasta}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
