"""Mi cuenta: cambio de contraseña."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

import ayudas as a
from sistema import seguridad

bp = Blueprint("cuenta", __name__)


@bp.route("/cuenta", methods=["GET", "POST"])
@a.login_requerido
def cuenta():
    if request.method == "POST":
        actual, nueva, repetir = (request.form.get(k, "") for k in ("actual", "nueva", "repetir"))
        if nueva != repetir:
            flash("Las contraseñas nuevas no coinciden.", "warning")
        else:
            ok, _ = a.ejecutar(seguridad.cambiar_password, a.usuario_actual(), actual, nueva)
            if ok:
                flash("Contraseña actualizada.", "success")
                return redirect(url_for("cuenta.cuenta"))
    return render_template("cuenta.html")
