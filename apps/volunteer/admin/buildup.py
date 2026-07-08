import random
from collections import Counter
from typing import ClassVar

from dateutil.rrule import DAILY, rrule
from flask import redirect, request, url_for
from flask_admin import expose
from flask_admin.actions import action
from flask_admin.form import Field
from flask_login import current_user
from wtforms import StringField
from wtforms.fields.datetime import DateTimeLocalField

from main import db, external_url
from models.user import User
from models.volunteer.buildup import (
    BuildupSignupKey,
    BuildupVolunteer,
    buildup_end,
    buildup_start,
    teardown_end,
    teardown_start,
)

from ..flask_admin_base import VolunteerBaseView, VolunteerModelView
from . import volunteer_admin

TOKEN_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


class BuildupSignupKeyModelView(VolunteerModelView):
    column_filters = ("team_name",)
    form_columns = ("token", "team_name", "min_arrival_date")
    form_overrides: ClassVar[dict[str, type[Field]] | None] = {"min_arrival_date": DateTimeLocalField}

    def create_form(self, obj=None):
        form = super().create_form(obj=obj)

        if not form.token.data:
            form.token.data = "".join(random.choices(TOKEN_ALPHABET, k=12))

        if not form.min_arrival_date.data:
            form.min_arrival_date.data = buildup_start()

        return form

    def get_edit_form(self):
        form = super().get_edit_form()
        form.url = StringField("URL", render_kw={"readonly": True})
        return form

    def edit_form(self, obj=None):
        form = super().edit_form(obj=obj)

        form.url.data = external_url("volunteer.buildup_register", token=form.token.data)
        if not form.token.render_kw:
            form.token.render_kw = {}

        form.token.render_kw["readonly"] = True
        return form

    @action("breakdown", "View Arrival Breakdown")
    def action_view_breakdown(self, ids):
        return redirect(url_for("volunteer_admin_breakdown.index", signup_key=ids))

    @action("volunteers", "View Volunteers")
    def action_view_volunteers(self, ids):
        return redirect(url_for("volunteer_admin_buildupvolunteer.index_view", signup_key=ids))


volunteer_admin.add_view(
    BuildupSignupKeyModelView(BuildupSignupKey, db, name="Signup keys", category="Buildup")
)


class BuildupVolunteerModelView(VolunteerModelView):
    form_excluded_columns = ("versions", "emergency_contact")
    can_view_details = True
    details_modal = True
    column_list = (
        "user.volunteer.nickname",
        "signup_key.team_name",
        "arrival_date",
        "departure_date",
        "vehicle_registration",
        "acked_health_and_safety_briefing_at",
        "recorded_on_site",
        "left_site",
    )
    column_filters = (
        "signup_key_token",
        "user.volunteer.nickname",
        "signup_key.team_name",
    )
    column_labels: ClassVar[dict[str, str]] = {
        "user.volunteer.nickname": "Name",
        "signup_key.team_name": "Team",
        "arrival_date": "Arrival",
        "departure_date": "Departure",
        "vehicle_registration": "Vehicle Reg",
        "acked_health_and_safety_briefing_at": "Registered at",
        "recorded_on_site": "On site",
        "left_site": "Left site",
    }

    def _modify_widget_args(self, form, obj=None, create=False):
        if not form.arrival_date.render_kw:
            form.arrival_date.render_kw = {}
        form.arrival_date.render_kw.update(
            **{
                "data-min-date": buildup_start(),
                "data-max-date": teardown_end(),
            }
        )
        if create:
            form.arrival_date.render_kw["data-start-date"] = buildup_end()

        if not form.departure_date.render_kw:
            form.departure_date.render_kw = {}
        form.departure_date.render_kw.update(
            **{
                "data-min-date": buildup_start(),
                "data-max-date": teardown_end(),
            }
        )
        if create:
            form.departure_date.render_kw["data-start-date"] = teardown_start()

        return form

    def create_form(self, obj=None):
        return self._modify_widget_args(super().create_form(obj), create=True)

    def edit_form(self, obj=None):
        return self._modify_widget_args(super().edit_form(obj))

    def render(self, *args, **kwargs):
        if details_columns := kwargs.pop("details_columns", None):
            if not current_user.has_permission("volunteer:admin_view_emergency_contact"):
                details_columns = [
                    (cid, cname) for cid, cname in details_columns if cid != "emergency_contact"
                ]
            kwargs["details_columns"] = details_columns
        return super().render(*args, **kwargs)

    def get_query(self):
        query = super().get_query()
        if signup_keys_strs := request.args.getlist("signup_key"):
            query = query.filter(BuildupVolunteer.signup_key_token.in_(signup_keys_strs))
        return query


volunteer_admin.add_view(
    BuildupVolunteerModelView(BuildupVolunteer, db, name="Volunteers", category="Buildup")
)


class BuildupVolunteerBreakdownView(VolunteerBaseView):
    @expose("/")
    def index(self):
        query = db.session.query(BuildupVolunteer)

        signup_keys = None
        if signup_keys_strs := request.args.getlist("signup_key"):
            signup_keys = (
                db.session.query(BuildupSignupKey).filter(BuildupSignupKey.token.in_(signup_keys_strs)).all()
            )
            query = query.filter(BuildupVolunteer.signup_key_token.in_(signup_keys_strs))

        days_data = []
        is_just_after_event = False
        earliest_buildup = query.order_by(BuildupVolunteer.arrival_date).first()
        if earliest_buildup is None:
            start = buildup_start()
        else:
            start = earliest_buildup.arrival_date
        for dt in rrule(DAILY, dtstart=start, until=teardown_end(), byhour=[6, 18]):
            if buildup_end() <= dt <= teardown_start():
                is_just_after_event = True
                continue
            predicted_volunteers = query.filter(
                (BuildupVolunteer.arrival_date <= dt) & (BuildupVolunteer.departure_date >= dt)
            )
            arrived_volunteers = query.filter(BuildupVolunteer.recorded_on_site <= dt)
            date_str = dt.date().strftime("%a %d-%b")
            am_or_pm = "AM" if dt.time().hour < 12 else "PM"
            days_data.append(
                {
                    "date_str": date_str,
                    "am_or_pm": am_or_pm,
                    "is_just_after_event": is_just_after_event,
                    "predicted_onsite": predicted_volunteers.count(),
                    "arrived_onsite": arrived_volunteers.count(),
                }
            )
            if is_just_after_event:
                is_just_after_event = False
        max_predicted = max(d["predicted_onsite"] for d in days_data)
        max_arrived = max(d["arrived_onsite"] for d in days_data)
        return self.render(
            "volunteer/admin/buildup_breakdown.html",
            days_data=days_data,
            max_predicted=max_predicted,
            max_arrived=max_arrived,
            signup_keys=signup_keys,
        )


volunteer_admin.add_view(
    BuildupVolunteerBreakdownView(name="Arrival breakdown", category="Buildup", endpoint="breakdown")
)


class DietaryRequirementsView(VolunteerBaseView):
    @expose("/")
    def index(self):
        query = (
            db.session.query(BuildupVolunteer)
            .order_by(BuildupVolunteer.arrival_date)
            .options(db.selectinload(BuildupVolunteer.user).selectinload(User.volunteer))
        )

        days_data = []
        is_just_after_event = False
        earliest_buildup = query.first()
        if earliest_buildup is None:
            start = buildup_start()
        else:
            start = earliest_buildup.arrival_date

        all_allergies = set()
        all_restrictions = set()

        for dt in rrule(DAILY, dtstart=start, until=teardown_end(), byhour=[6, 18]):
            if buildup_end() <= dt <= teardown_start():
                is_just_after_event = True
                continue
            predicted_volunteers = query.filter(
                (BuildupVolunteer.arrival_date <= dt) & (BuildupVolunteer.departure_date >= dt)
            )

            allergies = Counter()
            dietary_restrictions = Counter()

            for v in predicted_volunteers.all():
                assert v.user.volunteer
                for allergen in v.user.volunteer.allergies:
                    allergies[allergen] += 1

                for restriction in v.user.volunteer.dietary_restrictions:
                    dietary_restrictions[restriction] += 1

            all_allergies |= set(allergies.keys())
            all_restrictions |= set(dietary_restrictions.keys())

            date_str = dt.date().strftime("%a %d-%b")
            am_or_pm = "AM" if dt.time().hour < 12 else "PM"
            days_data.append(
                {
                    "date_str": date_str,
                    "am_or_pm": am_or_pm,
                    "is_just_after_event": is_just_after_event,
                    "allergies": allergies,
                    "dietary_restrictions": dietary_restrictions,
                    "predicted_onsite": predicted_volunteers.count(),
                }
            )
            if is_just_after_event:
                is_just_after_event = False

        other_allergies = []
        other_restrictions = []

        for v in query.all():
            assert v.user.volunteer
            if v.user.volunteer.allergies_other:
                other_allergies.append((v, v.user.volunteer.allergies_other))
            if v.user.volunteer.dietary_restrictions_other:
                other_restrictions.append((v, v.user.volunteer.dietary_restrictions_other))

        return self.render(
            "volunteer/admin/dietary.html",
            days_data=days_data,
            all_allergies=all_allergies,
            all_restrictions=all_restrictions,
            other_allergies=other_allergies,
            other_restrictions=other_restrictions,
        )


volunteer_admin.add_view(
    DietaryRequirementsView(name="Dietary requirements", category="Buildup", endpoint="dietary")
)
