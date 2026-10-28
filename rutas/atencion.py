"""Atención clínica: formulario del control con la lista de verificación del protocolo,
procedimientos, exámenes, eventos adversos y encuesta de satisfacción."""
from datetime import datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import base, clinico
from sistema.base import hoy

bp = Blueprint("atencion", __name__)

# Si es True, una atención incompleta NO se puede finalizar. Se deja en False porque, si el
# sistema bloqueara la finalización, el indicador de "registros completos" siempre sería 100 %
# y dejaría de medir algo (decisión de diseño de la Fase 2; conviene confirmarla con el asesor).
EXIGIR_COMPLETO = False

TIPOS_PROCEDIMIENTO = ["endoscopia digestiva alta", "colonoscopia", "CPRE", "otro"]
TIPOS_EXAMEN = ["laboratorio", "patologia", "imagen", "otro"]
TIPOS_EVENTO = ["Sangrado posbiopsia", "Reacción a la sedación", "Dolor abdominal posprocedimiento",
                "Pancreatitis pos-CPRE", "Reacción adversa a medicamento", "Caída del paciente en consultorio",
                "Otro (describir)"]
GRAVEDADES = ["leve", "moderado", "grave", "mortal"]
CAMPOS_TEXTO = ["motivo_consulta", "anamnesis", "examen_fisico", "tratamiento", "indicaciones", "observaciones"]


def _a_atencion(aid, tab=None):
    return redirect(url_for("atencion.trabajo", aid=aid) + (f"#{tab}" if tab else ""))


@bp.route("/atencion")
@a.permiso("atenciones.ver")
def lista():
    fecha = a.fecha_arg("fecha", hoy())
    citas, meta = [], {}
    puede_listar = a.tiene("citas.gestionar")
    if puede_listar:
        ok, citas = a.ejecutar(clinico.listar_citas, a.usuario_actual(), fecha, fecha, None, None)
        citas = [c for c in (citas if ok else []) if c["estado"] in ("programada", "asistio")]
        if citas:   # ¿qué citas ya tienen atención? (solo estado, no contenido clínico)
            meta = {m["cita_id"]: m for m in base.consultar(
                "SELECT id, cita_id, estado FROM atenciones WHERE cita_id = ANY(%s)", ([c["id"] for c in citas],))}
    return render_template("atencion_lista.html", fecha=fecha, citas=citas, meta=meta, puede_listar=puede_listar,
                           ahora=base.ahora().strftime("%H:%M"))


@bp.route("/atencion/iniciar/<int:cid>", methods=["POST"])
@a.permiso("atenciones.registrar")
def iniciar(cid):
    texto = request.form.get("llegada")
    try:
        llegada = time.fromisoformat(texto) if texto else base.ahora().time().replace(second=0, microsecond=0)
    except ValueError:
        flash("La hora de llegada no es válida.", "warning")
        return redirect(url_for("atencion.lista"))
    momento = datetime.combine(hoy(), llegada, base.TZ)
    if momento > base.ahora():
        flash("La hora de llegada no puede ser futura.", "warning")
        return redirect(url_for("atencion.lista"))
    ok, aid = a.ejecutar(clinico.iniciar_atencion, a.usuario_actual(), cid, momento)
    if not ok:
        return redirect(url_for("atencion.lista"))
    return redirect(url_for("atencion.trabajo", aid=aid))


@bp.route("/atencion/cita/<int:cid>")
@a.permiso("atenciones.ver")
def por_cita(cid):
    """Abre la atención de una cita (si ya existe) o vuelve a la lista de ese día."""
    fila = base.consultar("SELECT id FROM atenciones WHERE cita_id = %s", (cid,))
    if fila:
        return redirect(url_for("atencion.trabajo", aid=fila[0]["id"]))
    flash("Esta cita todavía no tiene atención. Solo el médico puede iniciarla.", "info")
    return redirect(url_for("atencion.lista"))


@bp.route("/atencion/<int:aid>")
@a.permiso("atenciones.ver")
def trabajo(aid):
    usuario = a.usuario_actual()
    ok, at = a.ejecutar(clinico.obtener_atencion, usuario, aid)
    if not ok:
        return redirect(url_for("atencion.lista"))
    finalizada = at["estado"] == "finalizada"
    puede_editar = a.tiene("atenciones.registrar")
    return render_template(
        "atencion.html", at=at, finalizada=finalizada, puede_editar=puede_editar,
        es_autor=puede_editar and at["medico_id"] == usuario["id"],
        diagnosticos=a.diagnosticos(), tipos_proc=TIPOS_PROCEDIMIENTO, tipos_examen=TIPOS_EXAMEN,
        tipos_evento=TIPOS_EVENTO, gravedades=GRAVEDADES,
        puede_evento=a.tiene("eventos.registrar"), puede_encuesta=a.tiene("citas.gestionar"))


@bp.route("/atencion/<int:aid>/guardar", methods=["POST"])
@a.permiso("atenciones.registrar")
def guardar(aid):
    f = request.form
    finalizar = f.get("accion") == "finalizar"
    datos = {c: f.get(c, "") for c in CAMPOS_TEXTO}
    datos["diagnostico_cie10"] = f.get("diagnostico_cie10") or None
    ids = [int(x) for x in (f.get("pasos") or "").split(",") if x.strip().isdigit()]
    pasos = {i: f.get(f"paso_{i}") == "1" for i in ids}
    ok, r = a.ejecutar(clinico.guardar_atencion, a.usuario_actual(), aid, datos, pasos,
                       finalizar=finalizar, exigir_completo=EXIGIR_COMPLETO)
    if ok:
        if finalizar and r["registro_completo"]:
            flash("Atención finalizada con el registro completo.", "success")
        elif finalizar:
            flash("Atención finalizada, pero faltan campos obligatorios: " + ", ".join(a.humano(c) for c in r["campos_faltantes"])
                  + ". Puede reabrirla para completarlos.", "warning")
        else:
            flash("Borrador guardado.", "success")
    return _a_atencion(aid)


@bp.route("/atencion/<int:aid>/reabrir", methods=["POST"])
@a.permiso("atenciones.registrar")
def reabrir(aid):
    ok, _ = a.ejecutar(clinico.reabrir_atencion, a.usuario_actual(), aid, request.form.get("motivo"))
    if ok:
        flash("Atención reabierta; el motivo quedó en la bitácora.", "warning")
    return _a_atencion(aid)


@bp.route("/atencion/<int:aid>/procedimiento", methods=["POST"])
@a.permiso("atenciones.registrar")
def procedimiento(aid):
    f = request.form
    ok, _ = a.ejecutar(clinico.registrar_procedimiento, a.usuario_actual(), aid, f.get("tipo"),
                       f.get("hallazgos"), f.get("conclusion"))
    if ok:
        flash("Procedimiento agregado.", "success")
    return _a_atencion(aid, "procedimientos")


@bp.route("/atencion/<int:aid>/examen", methods=["POST"])
@a.permiso("atenciones.registrar")
def examen(aid):
    f = request.form
    valor = (f.get("valor") or "").strip()
    try:
        numero = float(valor.replace(",", ".")) if valor else None
    except ValueError:
        flash("El valor numérico no es válido.", "warning")
        return _a_atencion(aid, "examenes")
    ok, _ = a.ejecutar(clinico.registrar_examen, a.usuario_actual(), aid, f.get("tipo"), f.get("nombre"),
                       f.get("resultado"), numero, f.get("unidad"))
    if ok:
        flash("Examen agregado.", "success")
    return _a_atencion(aid, "examenes")


@bp.route("/atencion/<int:aid>/evento", methods=["POST"])
@a.permiso("eventos.registrar")
def evento(aid):
    f = request.form
    tipo = f.get("otro") if (f.get("tipo") or "").startswith("Otro") else f.get("tipo")
    ok, _ = a.ejecutar(clinico.registrar_evento_adverso, a.usuario_actual(), aid, tipo, f.get("gravedad"),
                       f.get("descripcion"), a.entero_arg("procedimiento_id"), f.get("accion"))
    if ok:
        flash("Evento adverso registrado.", "warning")
    return _a_atencion(aid, "eventos")


@bp.route("/atencion/<int:aid>/encuesta", methods=["POST"])
@a.permiso("citas.gestionar")
def encuesta(aid):
    f = request.form
    ok, _ = a.ejecutar(clinico.registrar_encuesta, a.usuario_actual(), aid, a.entero_arg("puntaje", 0),
                       f.get("espera") == "1", f.get("comentario"))
    if ok:
        flash("Encuesta registrada. ¡Gracias!", "success")
    return _a_atencion(aid, "encuesta")
