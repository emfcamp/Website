from flask import Flask
from flaskext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'test'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'

login_manager = LoginManager()
login_manager.setup_app(app)

db = SQLAlchemy(app)

from models import *
from views import *

db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
