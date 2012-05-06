from main import db

class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String, nullable=False)
    reference = db.Column(db.String, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')

    def __init__(self, provider, reference):
        self.provider = provider
        self.reference = reference


class PaymentChange(db.Model):
    __tablename__ = 'payment_change'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String, nullable=False)

    def __init__(self, state):
        self.state = state
