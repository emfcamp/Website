from flask import Flask, render_template
from flaskext.login import LoginManager

app = Flask(__name__)
app.secret_key = 'test'
login_manager = LoginManager()
login_manager.setup_app(app)

@app.route("/")
def main():
    return render_template('main.html')

@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')

if __name__ == "__main__":
    app.run(debug=True)
