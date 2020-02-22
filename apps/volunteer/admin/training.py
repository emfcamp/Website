from ..flask_admin_base import FlaskVolunteerAdminAppMixin
from flask_admin.contrib.sqla import ModelView

from main import volunteer_admin, db
from models.volunteer.training import Training, TrainingQuestion, TrainingAnswer


class TrainingModelView(FlaskVolunteerAdminAppMixin, ModelView):

    can_delete = False
    can_view_details = True
    column_list = (
        "role",
        "name",
        "enabled",
    )
    details_modal = True
    form_columns = (
        "enabled",
        "name",
        "role",
        "pass_auto",
        "pass_mark",
        "url",
    )


volunteer_admin.add_view(TrainingModelView(Training, db.session, category="Training",))


class TrainingQuestionsView(FlaskVolunteerAdminAppMixin, ModelView):

    can_view_details = True
    column_list = (
        "training",
        "text",
        "order",
    )
    details_modal = True
    form_excluded_columns = (
        "answers",
        "versions",
    )


volunteer_admin.add_view(
    TrainingQuestionsView(
        TrainingQuestion, db.session, category="Training", name="Questions",
    )
)


class TrainingAnswersView(FlaskVolunteerAdminAppMixin, ModelView):

    can_view_details = True
    column_list = (
        "question",
        "text",
        "correct",
    )
    details_modal = True
    form_excluded_columns = ("versions",)


volunteer_admin.add_view(
    TrainingAnswersView(
        TrainingAnswer, db.session, category="Training", name="Answers",
    )
)
