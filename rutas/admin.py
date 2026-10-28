"""Administración: usuarios, bitácora de auditoría y accesos al sistema."""
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import base, seguridad
from sistema.base import hoy

bp = Blueprint("admin", __name__)
NOMBRES_BIT = {"created_at": "Fecha y hora", "usuario": "Usuario", "accion": "Acción", "entidad": "Entidad",
               "entidad_id": "N.º registro", "resultado": "Resultado", "ip": "IP"}
NOMBRES_ACC = {"created_at": "Fecha y hora", "email_intentado": "Correo", "resultado": "Resultado",
               "motivo": "Motivo", "ip": "IP"}


@bp.route("/admin")
@a.permiso("usuarios.administrar", "auditoria.ver")
def inicio_admin():
    return redirect(url_for("admin.usuarios") if a.tiene("usuarios.administrar") else url_for("admin.bitacora"))


@bp.route("/admin/usuarios")
@a.permiso("usuarios.administrar")
def usuarios():
    ok, filas = a.ejecutar(seguridad.listar_usuarios, a.usuario_actual())
    return render_template("admin_usuarios.html", filas=filas if ok else [], roles=a.roles_disponibles())


@bp.route("/admin/usuarios/crear", methods=["POST"])
@a.permiso("usuarios.administrar")
def crear():
    f = request.form
    if f.get("clave") != f.get("repetir"):
        flash("Las contraseñas no coinciden.", "warning")
    else:
        ok, _ = a.ejecutar(seguridad.crear_usuario, a.usuario_actual(), f.get("rol"), f.get("nombres"),
                           f.get("apellidos"), f.get("email"), f.get("clave"), f.get("colegiatura"), f.get("especialidad"))
        if ok:
            a.olvidar_catalogos()
            flash("Usuario creado. Pídale que cambie su contraseña en «Mi cuenta».", "success")
    return redirect(url_for("admin.usuarios"))


@bp.route("/admin/usuarios/<int:uid>/<accion>", methods=["POST"])
@a.permiso("usuarios.administrar")
def accion_usuario(uid, accion):
    usuario = a.usuario_actual()
    if accion == "desbloquear":
        ok, _ = a.ejecutar(seguridad.desbloquear_usuario, usuario, uid)
        mensaje = "Cuenta desbloqueada."
    elif accion in ("activar", "desactivar"):
        ok, _ = a.ejecutar(seguridad.cambiar_estado_usuario, usuario, uid, accion == "activar")
        mensaje = "Usuario activado." if accion == "activar" else "Usuario desactivado."
        a.olvidar_catalogos()
    else:
        return redirect(url_for("admin.usuarios"))
    if ok:
        flash(mensaje, "success")
    return redirect(url_for("admin.usuarios"))


def _filtros():
    desde = a.fecha_arg("desde", hoy() - timedelta(days=7))
    hasta = a.fecha_arg("hasta", hoy())
    limite = a.entero_arg("limite", 200)
    return desde, hasta, limite if limite in (200, 500, 1000) else 200


@bp.route("/admin/bitacora")
@a.permiso("auditoria.ver")
def bitacora():
    desde, hasta, limite = _filtros()
    entidad = request.args.get("entidad") or None
    entidades = [f["entidad"] for f in base.consultar(
        "SELECT DISTINCT entidad FROM bitacora_auditoria WHERE entidad IS NOT NULL ORDER BY 1")]
    ok, filas = a.ejecutar(seguridad.consultar_bitacora, a.usuario_actual(), desde, hasta, entidad, limite)
    return render_template("admin_bitacora.html", filas=filas if ok else [], desde=desde, hasta=hasta,
                           limite=limite, entidad=entidad, entidades=entidades)


@bp.route("/admin/bitacora.csv")
@a.permiso("auditoria.ver")
def csv_bitacora():
    desde, hasta, limite = _filtros()
    ok, filas = a.ejecutar(seguridad.consultar_bitacora, a.usuario_actual(), desde, hasta,
                           request.args.get("entidad") or None, limite)
    return a.descargar_csv(filas if ok else [], list(NOMBRES_BIT), NOMBRES_BIT, "bitacora_auditoria.csv")


@bp.route("/admin/accesos")
@a.permiso("auditoria.ver")
def accesos():
    desde, hasta, limite = _filtros()
    solo = request.args.get("todos") != "1"
    ok, filas = a.ejecutar(seguridad.consultar_accesos, a.usuario_actual(), desde, hasta, solo, limite)
    return render_template("admin_accesos.html", filas=filas if ok else [], desde=desde, hasta=hasta,
                           limite=limite, solo=solo)


@bp.route("/admin/accesos.csv")
@a.permiso("auditoria.ver")
def csv_accesos():
    desde, hasta, limite = _filtros()
    ok, filas = a.ejecutar(seguridad.consultar_accesos, a.usuario_actual(), desde, hasta,
                           request.args.get("todos") != "1", limite)
    return a.descargar_csv(filas if ok else [], list(NOMBRES_ACC), NOMBRES_ACC, "accesos.csv")
