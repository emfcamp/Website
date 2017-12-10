import flask_admin.base

_get_url = flask_admin.base.BaseView.get_url
_create_blueprint = flask_admin.base.BaseView.create_blueprint

def get_url(self, endpoint, **kwargs):
    # Yes, it's actually hardcoded
    if endpoint == 'admin.static':
        endpoint = '{}.static'.format(self.admin.endpoint_prefix)
    return _get_url(self, endpoint, **kwargs)

def create_blueprint(self, admin):
    if self.endpoint == admin.endpoint:
        self.endpoint = admin.endpoint_prefix
    else:
        self.url = self._get_view_url(admin, self.url)
        self.endpoint = '{}.{}'.format(admin.endpoint_prefix, self.endpoint)
    return _create_blueprint(self, admin)

flask_admin.base.BaseView.get_url = get_url
flask_admin.base.BaseView.create_blueprint = create_blueprint
flask_admin.base.AdminIndexView.get_url = get_url
flask_admin.base.AdminIndexView.create_blueprint = create_blueprint

