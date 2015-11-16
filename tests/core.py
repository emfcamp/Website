# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import os
import os.path
from main import create_app, db
from utils import CreateBankAccounts, CreateTickets


def get_app():
    app = create_app()
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    try:
        os.remove(os.path.join(root, 'var', 'test.db'))
    except OSError:
        pass
    os.environ['SETTINGS_FILE'] = os.path.join(root, 'config', 'test.cfg')
    with app.app_context():
        db.create_all()
        CreateBankAccounts().run()
        CreateTickets().run()

    return app.test_client(), app, db
