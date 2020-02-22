# coding=utf-8
from main import db


class Training(db.Model):
    __tablename__ = "volunteer_training"
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    role_id = db.Column(db.Integer, db.ForeignKey("volunteer_role.id"), nullable=False)
    pass_auto = db.Column(db.Boolean, nullable=False, default=False)
    pass_mark = db.Column(db.Integer, nullable=False, default=0)
    url = db.Column(db.String, nullable=False, default="")

    # external object references
    role = db.relationship("Role", backref="training")
    questions = db.relationship("TrainingQuestion")

    def __repr__(self):
        return "<Training {0}>".format(self.name)

    def __str__(self):
        return self.name

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
        }

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Training.id).all()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get(id)

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()


class TrainingQuestion(db.Model):
    __tablename__ = "volunteer_training_question"
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    training_id = db.Column(
        db.Integer, db.ForeignKey("volunteer_training.id"), nullable=False
    )
    order = db.Column(db.Integer, nullable=False, default=0)
    text = db.Column(db.String, nullable=False, default="")

    # external object references
    answers = db.relationship("TrainingAnswer")
    training = db.relationship("Training")

    def __repr__(self):
        return "<TrainingQuestion {0}>".format(self.text)

    def __str__(self):
        return self.text


class TrainingAnswer(db.Model):
    __tablename__ = "volunteer_training_answer"
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("volunteer_training_question.id"), nullable=False
    )
    text = db.Column(db.String, nullable=False, default="")
    correct = db.Column(db.Boolean, nullable=False, default=False)

    # external object references
    question = db.relationship("TrainingQuestion")

    def __repr__(self):
        return "<TrainingQuestion {0}>".format(self.text)

    def __str__(self):
        return self.text
