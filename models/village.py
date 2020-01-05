from main import db


class Village(db.Model):
    __tablename__ = "village"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String, nullable=False, unique=True)
    description = db.Column(db.String)

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.filter_by(id=id).one_or_none()

    def admins(self):
        return [mem.user for mem in self.members if mem.admin]

    def __repr__(self):
        return f"<Village '{self.name}' (id: {self.id})>"


class VillageMember(db.Model):
    __tablename__ = "village_member"

    id = db.Column(db.Integer, primary_key=True)

    village_id = db.Column(db.Integer, db.ForeignKey("village.id"), nullable=False)
    village = db.relationship("Village", backref="members")

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("village", uselist=False))

    admin = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<VillageMember {self.user} member of {self.village}>"


class VillageRequirements(db.Model):
    __tablename__ = "village_requirements"

    village_id = db.Column(db.Integer, db.ForeignKey("village.id"), primary_key=True)
    village = db.relationship(
        "Village", backref=db.backref("requirements", uselist=False)
    )

    num_attendees = db.Column(db.Integer)
    size_sqm = db.Column(db.Integer)

    power_requirements = db.Column(db.String)
    noise = db.Column(db.String)

    structures = db.Column(db.String)
