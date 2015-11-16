from main import app
from views import feature_flag

from flask import render_template

@app.route("/radio", methods=['GET'])
@feature_flag('RADIO')
def radio():
    return render_template('radio.html')

