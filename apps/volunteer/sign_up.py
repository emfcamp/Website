from flask import (
    current_app as app,
)
from flask import (
    flash,
    redirect,
    render_template,
    render_template_string,
    request,
    url_for,
)
from flask_login import current_user
from markupsafe import Markup
from wtforms import BooleanField, Field, StringField, SubmitField
from wtforms.form import BaseForm
from wtforms.utils import unset_value
from wtforms.validators import DataRequired, Email, ValidationError

from apps.common import get_next_url
from main import db
from models.user import User
from models.volunteer import Volunteer as VolunteerUser

from ..common import create_current_user, feature_flag
from ..common.fields import TelField
from ..common.forms import Form
from . import v_user_required, volunteer

# 14 regulated allergens: https://www.food.gov.uk/safety-hygiene/food-allergy-and-intolerance
ALLERGEN_CHOICES = [
    ("celery", "Celery"),
    ("gluten", "Cereals containing gluten"),
    ("crustaceans", "Crustaceans (inc. crabs, lobster, prawns)"),
    ("eggs", "Eggs"),
    ("fish", "Fish"),
    ("lupin", "Lupin"),
    ("milk", "Milk"),
    ("molluscs", "Molluscs (inc. mussels, land snails, squid, oyster sauce)"),
    ("mustard", "Mustard"),
    ("tree_nuts", "Tree nuts (inc. cashews, almonds, hazelnuts)"),
    ("peanuts", "Peanuts"),
    ("sesame", "Sesame seeds"),
    ("soya", "Soya"),
    ("sulphites", "Sulphur dioxide/sulphites"),
]

DIETARY_RESTRICTIONS_CHOICES = [
    ("vegan", "Vegan (plant based)"),
    ("vegetarian", "Vegetarian (no meat or fish"),
]


class MultipleChoiceAndOtherWidget:
    def __call__(self, field, **kwargs):
        html = ["<ul>"]
        for subfield in field:
            if subfield.name.endswith("-other"):
                html.append(f"<li>{subfield.label} {subfield(class_='form-control')}</li>")
            else:
                html.append(f"<li>{subfield()} {subfield.label}</li>")
        html.append("</ul>")
        return Markup("".join(html))


class MultipleChoiceAndOtherField(Field):
    widget = MultipleChoiceAndOtherWidget()

    def __init__(self, label, choices, **kwargs):
        super().__init__(label, **kwargs)
        self._choices = choices
        self._fields = {key: BooleanField(label) for key, label in choices}
        self._fields["other"] = StringField("Other")
        self._form = None

    def process(self, formdata, data=unset_value, extra_filters=None):
        prefix = f"{self.name}-"
        self._form = BaseForm(self._fields, prefix=prefix)
        kwargs = {}
        if data is not unset_value:
            downstream_data = {}
            for key in data:
                downstream_data[key] = True
            kwargs["data"] = downstream_data
        self._form.process(formdata=formdata, **kwargs)

    def validate(self, form, extra_validators=tuple()):
        return self._form.validate()

    def populate_obj(self, obj, name):
        setattr(obj, name, self.data)
        setattr(obj, f"{name}_other", self.data_other)

    def __iter__(self):
        return iter(self._form)

    def __getitem__(self, name):
        return self._form[name]

    def __getattr__(self, name):
        return getattr(self._form, name)

    @property
    def data(self):
        selected_choices = set()
        for choice_key, _ in self._choices:
            if self._form[choice_key].data:
                selected_choices.add(choice_key)
        return selected_choices

    @property
    def data_other(self):
        return self._form["other"].data

    @data_other.setter
    def data_other(self, value):
        self._form["other"].data = value

    @property
    def errors(self):
        return self._form.errors


class VolunteerSignUpForm(Form):
    nickname = StringField("Name", [DataRequired()])
    volunteer_email = StringField("Email", [Email(), DataRequired()])
    over_18 = BooleanField("I'm at least 18 years old")
    volunteer_phone = TelField("Phone", min_length=3)
    allergies = MultipleChoiceAndOtherField(
        "Allergies", ALLERGEN_CHOICES, description="Anything which will cause health issues if ingested"
    )
    dietary_restrictions = MultipleChoiceAndOtherField("Dietary Restrictions", DIETARY_RESTRICTIONS_CHOICES)
    sign_up = SubmitField("Sign Up")
    save = SubmitField("Save")

    def process(self, formdata=None, obj=None, **kwargs):
        super().process(formdata=formdata, obj=obj, **kwargs)
        if obj is not None:
            self.allergies.data_other = obj.allergies_other
            self.dietary_restrictions.data_other = obj.dietary_restrictions_other

    def validate_volunteer_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            volunteer_url = url_for(".sign_up")

            msg = Markup(
                render_template_string(
                    """You already have an account.
                Please <a href="{{ url }}" target="_new">click here</a> to log in.""",
                    url=url_for("users.login", next=volunteer_url, email=field.data),
                )
            )

            raise ValidationError(msg)


def update_volunteer_from_form(volunteer, form):
    volunteer.nickname = form.nickname.data
    volunteer.volunteer_email = form.volunteer_email.data
    volunteer.volunteer_phone = form.volunteer_phone.data
    volunteer.over_18 = form.over_18.data
    volunteer.allergies = form.allergies.data
    volunteer.allergies_other = form.allergies.data_other
    volunteer.dietary_restrictions = form.dietary_restrictions.data
    volunteer.dietary_restrictions_other = form.dietary_restrictions.data_other
    return volunteer


@volunteer.route("/sign-up", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
def sign_up():
    form = VolunteerSignUpForm()

    if current_user.is_authenticated and VolunteerUser.get_for_user(current_user):
        return redirect(url_for(".choose_role"))

    if request.method != "POST" and current_user.is_authenticated:
        form.volunteer_email.data = current_user.email
        form.nickname.data = current_user.name
        # Can't try to process age, as that's only submitted as part of the outreach questions

    if form.validate_on_submit():
        if current_user.is_anonymous:
            create_current_user(form.volunteer_email.data, form.nickname.data)

        new_volunteer = VolunteerUser()
        new_volunteer.user_id = current_user.id
        new_volunteer = update_volunteer_from_form(new_volunteer, form)
        db.session.add(new_volunteer)

        # On sign up give user 'volunteer' permission (+ managers etc.)
        current_user.grant_permission("volunteer:user")

        db.session.commit()
        app.logger.info("Add volunteer: %s", new_volunteer)
        flash("Thank you for signing up!", "message")

        return redirect(get_next_url(default=url_for(".choose_role")))

    return render_template("volunteer/sign-up.html", user=current_user, form=form)


@volunteer.route("/account", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
@v_user_required
def account():
    if current_user.is_anonymous:
        return redirect(url_for(".sign_up"))

    volunteer = VolunteerUser.get_for_user(current_user)
    if volunteer is None:
        return redirect(url_for(".sign_up"))

    form = VolunteerSignUpForm(obj=volunteer)

    if form.validate_on_submit():
        update_volunteer_from_form(volunteer, form)
        db.session.commit()
        flash("Your details have been updated", "info")
        return redirect(url_for(".account"))

    return render_template("volunteer/account.html", user=current_user, form=form)
