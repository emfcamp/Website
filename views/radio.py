from main import app
from views import feature_flag

from flask import render_template

@feature_flag('RADIO')
@app.route("/radio", methods=['GET'])
def radio():
    return render_template('radio.html')

