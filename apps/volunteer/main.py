# encoding=utf-8
from flask import redirect, url_for

from . import volunteer
from ..common import feature_flag

@feature_flag('VOLUNTEERS_SIGNUP')
@volunteer.route('/')
def main():
    return redirect(url_for('.sign_up'))
