""" Villages admin.

    NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""
from flask import render_template, abort

from models.village import Village

from ..common import require_permission
from . import villages

village_admin_required = require_permission("villages")


@villages.route("/admin")
@village_admin_required
def admin():
    villages = sorted(Village.query.all(), key=lambda v: v.name)

    return render_template("villages/admin/list.html", villages=villages)


@villages.route("/admin/village/<int:village_id>")
@village_admin_required
def admin_village(village_id):
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    return render_template("villages/admin/info.html", village=village)
