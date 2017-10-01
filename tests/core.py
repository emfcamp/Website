# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import os
import os.path
from main import create_app, db
from utils import CreateBankAccounts, CreateTickets


def get_app():
    if 'SETTINGS_FILE' not in os.environ:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        os.environ['SETTINGS_FILE'] = os.path.join(root, 'config', 'test.cfg')

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
