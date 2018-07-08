# encoding=utf-8
from flask import render_template

from . import volunteers

@volunteers.route('/')
def main():
    return render_template('volunteers/main.html')
