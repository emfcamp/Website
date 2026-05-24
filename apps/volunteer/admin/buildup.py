import random
from typing import ClassVar

from dateutil.rrule import DAILY, rrule
from flask_admin import expose
from flask_admin.form import Field
from wtforms import StringField
from wtforms.fields.datetime import DateTimeLocalField

from main import db, external_url
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


volunteer_admin.add_view(
    BuildupSignupKeyModelView(BuildupSignupKey, db, name="Signup keys", category="Buildup")
)


class BuildupVolunteerModelView(VolunteerModelView):
    form_excluded_columns = ("versions",)

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


volunteer_admin.add_view(
    BuildupVolunteerModelView(BuildupVolunteer, db, name="Volunteers", category="Buildup")
)


class BuildupVolunteerBreakdownView(VolunteerBaseView):
    @expose("/")
    def index(self):
        days_data = []
        is_just_after_event = False
        earliest_buildup = db.session.query(BuildupVolunteer).order_by(BuildupVolunteer.arrival_date).first()
        if earliest_buildup is None:
            start = buildup_start()
        else:
            start = earliest_buildup.arrival_date
        for dt in rrule(DAILY, dtstart=start, until=teardown_end(), byhour=[6, 18]):
            if buildup_end() <= dt <= teardown_start():
                is_just_after_event = True
                continue
            predicted_volunteers = db.session.query(BuildupVolunteer).filter(
                (BuildupVolunteer.arrival_date <= dt) & (BuildupVolunteer.departure_date >= dt)
            )
            arrived_volunteers = db.session.query(BuildupVolunteer).filter(
                BuildupVolunteer.recorded_on_site <= dt
            )
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
        )


volunteer_admin.add_view(
    BuildupVolunteerBreakdownView(name="Arrival breakdown", category="Buildup", endpoint="breakdown")
)
