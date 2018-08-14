# encoding=utf-8
from flask import redirect, url_for

from . import volunteer
from ..common import feature_flag

@volunteer.route('/')
@feature_flag('VOLUNTEERS_SIGNUP')
def main():
    return redirect(url_for('.sign_up'))
