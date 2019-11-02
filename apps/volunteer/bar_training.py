from urllib.parse import urlencode
from hashlib import sha256
import hmac
import json

from flask import request, current_app as app, abort, render_template
from flask_login import current_user
import requests

from main import csrf, db, external_url
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer
from models.site_state import event_start
from models.user import User
from . import v_user_required, volunteer


TYPEFORM_BASE = "https://api.typeform.com"


@volunteer.route("/bar-training")
@v_user_required
def bar_training():
    bar = Role.query.filter_by(name="Bar").one()
    volunteer = Volunteer.get_for_user(current_user)

    trained = bar in volunteer.trained_roles

    params = {"token": current_user.bar_training_token, "name": current_user.name}
    url = app.config["BAR_TRAINING_FORM"] + "?" + urlencode(params)
    return render_template(
        "volunteer/training/bar-training.html", url=url, trained=trained
    )


@volunteer.route("/bar-training/check")
@v_user_required
def bar_training_check():
    volunteer = Volunteer.get_for_user(current_user)
    bar = Role.query.filter_by(name="Bar").one()
    return json.dumps(bar in volunteer.trained_roles)


@csrf.exempt
@volunteer.route("/bar-training/webhook/<tag>", methods=["GET", "POST"])
def bar_training_webhook(tag):
    if not hmac.compare_digest(get_auth_tag(), tag):
        abort(401)

    if request.method == "GET":
        return ("", 200)

    app.logger.debug("Bar training webhook called with %s", request.data)
    json_data = json.loads(request.data.decode("utf-8"))
    if json_data.get("event_type") != "form_response":
        # Don't care about this event type
        return ("", 200)

    response = json_data["form_response"]
    form_id = response["form_id"]
    if form_id != app.config["BAR_TRAINING_FORM"].rsplit("/", 1)[1]:
        return ("", 200)

    app.logger.info("Received form with hidden parameters %s", response["hidden"])
    token = response["hidden"].get("token")
    if not token:
        return ("", 200)
    user = User.get_by_bar_training_token(token)

    if not user.volunteer:
        return ("", 200)

    assert response["definition"]["id"] == form_id

    # response['calculated']['score'] is the number of answered questions
    # the "correct" answers have just been implemented as flow redirects

    answers = response["answers"]
    actual_answers = {
        "IqrW3FemheSD": "More than 0.5%",
        "tp0LL9XwEu41": "Protection of the environment",
        "tb9aGkLhJCJ0": "In day-to-day control of a particular licensed premises",
        "yB9izDMlu8N6": "No",
        "xy8AJqMKZAOH": "PASS hologram",
        "YHOch7ksAKax": "£90",
        "YX1fDJQOKOmQ": "60 minutes",
        "z5RRMJhZiYJG": "Details of the licensable activities to be held at the premises",
        "bmfSCzY4xQHe": "Outside the times stated in the premises licence",
        "ODyrmHU3XR2f": "2",
        "lToop6d3nun2": "18",
        "iZeKUVN9n33f": "Staggering or an inability to walk",
    }
    answers = {}
    for answer in response["answers"]:
        if answer["type"] == "choice":
            answers[answer["field"]["id"]] = answer["choice"]["label"]

    correct_answers = [id for id, a in answers.items() if actual_answers[id] == a]

    if len(correct_answers) == len(actual_answers):
        app.logger.info("%s passed the training", user)
        bar = Role.query.filter_by(name="Bar").one()
        bar.trained_volunteers.append(Volunteer.get_for_user(user))
        db.session.commit()

    app.logger.info("%s failed the training", user)

    return ("", 200)


def get_auth_tag():
    tag = "emf-{}-".format(event_start().year)
    msg = b"bar-training-" + tag.encode("utf-8")
    tag += hmac.new(
        app.config["SECRET_KEY"].encode("utf-8"), msg, digestmod=sha256
    ).hexdigest()
    return tag


def typeform_headers(**kwargs):
    kwargs.update({"Authorization": "Bearer " + app.config["BAR_TRAINING_TOKEN"]})
    return kwargs


def create_bar_training_webhook():
    # This doesn't work, despite documentation and consistent return value

    _, form_id = app.config["BAR_TRAINING_FORM"].rsplit("/", 1)

    webhook_url = TYPEFORM_BASE + "/forms/{}/webhooks/{}".format(
        form_id, get_auth_tag()
    )
    response = requests.get(webhook_url, headers=typeform_headers())
    if response.status_code == 404:
        url = external_url("volunteer.bar_training_webhook", tag=get_auth_tag())
        args = {"url": url, "enabled": True}
        response = requests.put(
            webhook_url, json.dumps(args), headers=typeform_headers()
        )

    response.raise_for_status()
    if response.status_code == 200:
        return response.json()["id"]
