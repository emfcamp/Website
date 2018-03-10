# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import os
import os.path
import shutil
from main import create_app, db
from utils import CreateBankAccounts, CreateTickets


def get_app():
    if 'SETTINGS_FILE' not in os.environ:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        os.environ['SETTINGS_FILE'] = os.path.join(root, 'config', 'test.cfg')

    prometheus_dir = '/tmp/emf_test_prometheus'
    os.environ['prometheus_multiproc_dir'] = prometheus_dir

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

    app = create_app()

    with app.app_context():
        try:
            db.session.close()
        except:
            pass

        try:
            db.drop_all()
        except:
            pass

        db.create_all()
        CreateBankAccounts().run()
        CreateTickets().run()

    return app.test_client(), app, db
