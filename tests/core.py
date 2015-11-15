# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import os
import os.path


def get_app():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    try:
        os.remove(os.path.join(root, 'var', 'test.db'))
    except OSError:
        pass
    os.environ['SETTINGS_FILE'] = os.path.join(root, 'config', 'test.cfg')
    from main import app, db
    db.create_all()
    from utils import CreateBankAccounts, CreateTickets
    CreateBankAccounts().run()
    CreateTickets().run()

    return app.test_client(), db
