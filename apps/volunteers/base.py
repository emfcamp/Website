from flask import current_app as app

from flask_admin import BaseView, AdminIndexView
from flask_admin.contrib.sqla import ModelView

# Flask-Admin requires these methods to be overridden, but doesn't let you set a base meta
# This is annoying as there's no safe way to stop someone accidentally using a base class
class FlaskVolunteerAppMixin:
    def is_accessible(self):
        # FIXME. Should probably separate all/some of the permissions for this
        return True

    def inaccessible_callback(self, name, **kwargs):
        return app.login_manager.unauthorized()

    def get_url(self, endpoint, **kwargs):
        # Hack to use some of the stuff set up for admin
        if (endpoint == 'volunteers.static') or (endpoint == 'admin.static'):
            endpoint = 'admin_new.static'
        return super().get_url(endpoint, **kwargs)

    def create_blueprint(self, admin):
        if self.endpoint == admin.endpoint:
            self.endpoint = admin.endpoint_prefix
        else:
            self.url = self._get_view_url(admin, self.url)
            self.endpoint = '{}.{}'.format(admin.endpoint_prefix, self.endpoint)
        return super().create_blueprint(admin)

class VolunteerBaseView(FlaskVolunteerAppMixin, BaseView):
    pass

class VolunteerIndexView(FlaskVolunteerAppMixin, AdminIndexView):
    pass

class VolunteerModelView(FlaskVolunteerAppMixin, ModelView):
    pass
