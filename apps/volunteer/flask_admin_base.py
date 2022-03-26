from flask import abort
from flask_login import current_user
from flask_admin import BaseView, AdminIndexView
from flask_admin.contrib.sqla import ModelView

# Flask-Admin requires these methods to be overridden, but doesn't let you set a base meta
# This is annoying as there's no safe way to stop someone accidentally using a base class
class FlaskVolunteerAdminAppMixin:
    def is_accessible(self):
        if current_user.is_authenticated:
            if current_user.has_permission("volunteer:admin"):
                return True
        return False

    def inaccessible_callback(self, name, **kwargs):
        abort(404)

    def get_url(self, endpoint, **kwargs):
        # Hack to use some of the stuff set up for admin
        if (endpoint == "volunteer_admin.static") or (endpoint == "admin.static"):
            endpoint = "volunteer_admin.static"
        return super().get_url(endpoint, **kwargs)

    def create_blueprint(self, admin):
        if self.endpoint == admin.endpoint:
            self.endpoint = admin.endpoint_prefix
        else:
            self.url = self._get_view_url(admin, self.url)
            self.endpoint = "{}_{}".format(admin.endpoint_prefix, self.endpoint)
        return super().create_blueprint(admin)


class VolunteerBaseView(FlaskVolunteerAdminAppMixin, BaseView):
    pass


class VolunteerAdminIndexView(FlaskVolunteerAdminAppMixin, AdminIndexView):
    # Yes this is should use url_for, but apparently this code's on the way out
    extra_css = ["/static/css/flask-admin.css"]


class VolunteerModelView(FlaskVolunteerAdminAppMixin, ModelView):
    pass
