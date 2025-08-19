from typing import ClassVar

from dateutil.rrule import DAILY, rrule
from flask_admin import expose

from main import db
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


class BuildupSignupKeyModelView(VolunteerModelView):
    column_filters: ClassVar[list[str]] = ["team_name"]
    form_columns: ClassVar[list[str]] = ["token", "team_name"]

    def edit_form(self, obj=None):
        form = super().edit_form(obj=obj)
        if not form.token.render_kw:
            form.token.render_kw = {}
        form.token.render_kw["readonly"] = True
        return form


volunteer_admin.add_view(
    BuildupSignupKeyModelView(BuildupSignupKey, db.session, name="Signup keys", category="Buildup")
)


class BuildupVolunteerModelView(VolunteerModelView):
    form_excluded_columns: ClassVar[list[str]] = ["versions"]

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
    BuildupVolunteerModelView(BuildupVolunteer, db.session, name="Volunteers", category="Buildup")
)


class BuildupVolunteerBreakdownView(VolunteerBaseView):
    @expose("/")
    def index(self):
        days_data = []
        is_just_after_event = False
        for dt in rrule(DAILY, dtstart=buildup_start(), until=teardown_end(), byhour=[6, 18]):
            if buildup_end() <= dt <= teardown_start():
                is_just_after_event = True
                continue
            predicted_volunteers = BuildupVolunteer.query.filter(
                (BuildupVolunteer.arrival_date <= dt) & (BuildupVolunteer.departure_date >= dt)
            )
            arrived_volunteers = BuildupVolunteer.query.filter(BuildupVolunteer.recorded_on_site <= dt)
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
