"""Inicio y cierre de sesión."""
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

import ayudas as a
from sistema import seguridad

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if a.usuario_actual():
        return redirect(url_for("inicio.inicio"))
    if request.method == "POST":
        ip, agente = a.ip_y_agente()
        ok, r = a.ejecutar(seguridad.autenticar, request.form.get("correo"), request.form.get("clave"), ip, agente)
        if ok and r["ok"]:
            usuario = dict(r["usuario"])
            usuario["permisos"] = sorted(usuario["permisos"])   # la sesión guarda listas, no conjuntos
            csrf = session.get("_csrf")
            session.clear()                                     # sesión nueva tras autenticar
            session["usuario"] = usuario
            session["_ultima"] = time.time()
            if csrf:
                session["_csrf"] = csrf
            siguiente = request.args.get("siguiente") or ""
            if siguiente.startswith("/") and not siguiente.startswith("//") and not siguiente.startswith("/login"):
                return redirect(siguiente.rstrip("?"))
            return redirect(url_for("inicio.inicio"))
        if ok:
            flash(r["mensaje"], "danger")   # clave incorrecta, cuenta bloqueada, etc.
    return render_template("login.html", correo=request.form.get("correo", ""))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
