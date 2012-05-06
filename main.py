from flask import Flask
from flaskext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config.from_envvar('SETTINGS_FILE')

login_manager = LoginManager()
login_manager.setup_app(app)

db = SQLAlchemy(app)

from views import *
from models import *
db.create_all()

@login_manager.user_loader
def load_user(userid):
    return User.query.filter_by(id=userid).first()

if __name__ == "__main__":
    app.run()
