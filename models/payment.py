from main import db

class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship("User", backref="payments")
    provider = db.Column(db.String, nullable=False)
    reference = db.Column(db.String, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    ticket = db.relationship("Ticket", backref="payments")

    def __init__(self, provider, reference):
        self.provider = provider
        self.reference = reference


class PaymentChange(db.Model):
    __tablename__ = 'payment_change'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    payment = db.relationship("Payment", backref="changes")
    timestamp = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String, nullable=False)

    def __init__(self, state):
        self.state = state
