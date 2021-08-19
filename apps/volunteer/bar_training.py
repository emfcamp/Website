import json
import os
import markdown
from . import v_user_required, volunteer

from flask_login import current_user
from flask import render_template, flash, redirect
from flask import url_for, current_app as app, abort
from main import db

from wtforms import SubmitField, RadioField, FormField, FieldList
from wtforms.validators import InputRequired, ValidationError
from ..common.forms import Form, HiddenIntegerField

from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer


# TODO: Make template (bar-training.html) pretty
# TODO: Paginate template using JavaScript
# TODO: Add proper validation (using JavaScript?), at a minimum ensure that
# the user can clearly see which questions are invalid.
# TODO: Implement Jinja tags in Markdown content so that static images can be served


def build_questions(training_json):
    """
    Assigns specific IDs to questions and answers so that we can determine which
    questions need re-adding to WTForms when a POST submission is sent. Also helps
    us determine the answers. WTForms is a bit of a nightmare with dynamic forms!
    """
    questions = {}
    page_num = 1
    question_id = 0
    answer_id = 0

    for page in training_json["pages"]:
        for question in page["questions"]:
            questions[question_id] = {}
            questions[question_id]["question"] = question["question"]
            questions[question_id]["page"] = page_num
            questions[question_id]["choices"] = []

            for a in question["answers"]:
                answer = (
                    str(answer_id),
                    a["answer"],
                )  # RadioField requires a tuple with (id, text)

                if a["correct"]:
                    questions[question_id]["correct"] = answer_id
                answer_id += 1
                questions[question_id]["choices"].append(answer)

            question_id += 1

        page_num += 1

    return questions


def load_training_json(path):
    file_path = os.path.abspath(os.path.join(__file__, "..", "..", "..", path))
    if not os.path.exists(file_path):
        return None

    return json.load(open(file_path, "r"))


def load_training_markdown(path):
    """
    Takes a file path for a Markdown file (relative to project root)
    and returns the HTML (from Markdown) for that file.
    """
    file_path = os.path.abspath(os.path.join(__file__, "..", "..", "..", path))
    if not os.path.exists(file_path):
        return None

    with open(file_path) as md_file:
        md_content = md_file.read()

    return markdown.markdown(md_content)


def check_answer_correct(form, question):
    if not question_data[form.question_id.data]["correct"] == int(question.data):
        raise ValidationError("This answer is not correct.")


class QuestionForm(Form):
    question_id = HiddenIntegerField("Answer ID")
    answers = RadioField(
        "Answers",
        [InputRequired(message="This question is unanswered."), check_answer_correct],
    )


class TrainingForm(Form):
    questions = FieldList(FormField(QuestionForm))
    submit = SubmitField("Complete training")

    def add_questions(self, question_data):
        """
        Check if a specific question already exists in the form (such as in a POST
        request) and if not, add the question to the form. Then iterate through
        all questions and enrich the question data.
        """

        # Check if the question already exists in the form, if not add it
        for qid in question_data.keys():
            question_exists = False
            for q in self.questions:
                if q.question_id.data == qid:
                    question_exists = True

            if not question_exists:
                self.questions.append_entry()
                self.questions[-1].question_id.data = qid

        # We should now have a form with the right amount of questions, add data to them
        for q in self.questions:
            data = question_data[int(q.question_id.data)]
            q.answers.choices = data["choices"]
            q.question = data["question"]
            q.page = data["page"]


@volunteer.route("/bar-training", methods=["GET", "POST"])
@v_user_required
def bar_training():
    bar = Role.query.filter_by(name="Bar").one()
    volunteer = Volunteer.get_for_user(current_user)
    trained = bar in volunteer.trained_roles

    training_json = load_training_json(app.config.get("BAR_TRAINING_JSON"))
    if training_json is None:  # Error loading training data
        app.logger.error(
            f"Bar training failed -- unable to load JSON: '{app.config.get('BAR_TRAINING_JSON')}'"
        )
        abort(404)

    global question_data  # Otherwise we can't access it in the form validator
    question_data = build_questions(training_json)
    form = TrainingForm()
    form.add_questions(question_data)

    if form.validate_on_submit():
        if trained:  # The user might be re-doing the traing, no need to rewrite DB
            flash("You answered all the questions correctly!")
        else:
            app.logger.info(f"{str(current_user)} passed the bar training.")
            bar.trained_volunteers.append(volunteer)
            db.session.commit()
            flash("Your completion of bar training has been saved.")
        return redirect(url_for(".bar_training"))

    # The template takes a list of pages which it will build sequentially, start
    # building this list now.
    pages = []
    page_num = 0

    for json_page in training_json["pages"]:
        page = {}
        page_num += 1
        page["number"] = page_num
        page["content"] = load_training_markdown(json_page["content"])

        if page["content"] is None:
            app.logger.error(
                f"Bar training failed -- unable to load Markdown: '{json_page['content']}'"
            )
            abort(404)

        page["questions"] = json_page["questions"]
        pages.append(page)

    return render_template(
        "volunteer/training/bar-training.html",
        trained=trained,
        form=form,
        pages=pages,
        last_page=len(pages),
        volunteer=volunteer,
    )
