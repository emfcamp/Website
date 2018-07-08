# encoding=utf-8
from flask import render_template

from . import volunteer

@volunteer.route('/')
def main():
    return render_template('volunteer/main.html')
