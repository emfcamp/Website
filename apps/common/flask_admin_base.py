from flask import current_app as app

from flask_login import current_user
from flask_admin import BaseView, AdminIndexView
from flask_admin.contrib.sqla import ModelView

# Flask-Admin requires these methods to be overridden, but doesn't let you set a base meta
# This is annoying as there's no safe way to stop someone accidentally using a base class
class FlaskAdminAppMixin:
    def is_accessible(self):
        if current_user.is_authenticated:
            if current_user.has_permission('admin'):
                return True
        return False

    def inaccessible_callback(self, name, **kwargs):
        return app.login_manager.unauthorized()

    def get_url(self, endpoint, **kwargs):
        # Yes, it's actually hardcoded
        if endpoint == 'admin.static':
            endpoint = '{}.static'.format(self.admin.endpoint_prefix)
        return super().get_url(endpoint, **kwargs)

    def create_blueprint(self, admin):
        if self.endpoint == admin.endpoint:
            self.endpoint = admin.endpoint_prefix
        else:
            self.url = self._get_view_url(admin, self.url)
            self.endpoint = '{}.{}'.format(admin.endpoint_prefix, self.endpoint)
        return super().create_blueprint(admin)

class AppBaseView(FlaskAdminAppMixin, BaseView):
    pass

class AppAdminIndexView(FlaskAdminAppMixin, AdminIndexView):
    pass

class AppModelView(FlaskAdminAppMixin, ModelView):
    pass


