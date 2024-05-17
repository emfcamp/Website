from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from . import BaseModel
from .product import Product


class ArrivalsView(BaseModel):
    """An analog to a ProductView, except for checking in items rather than selling them.""" 

    __tablename__ = "arrivals_view"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, index=True)

    required_permission_id = db.Column(db.Integer, db.ForeignKey("permission.id"), index=True, nullable=False)
    required_permission = db.relationship("Permission")

    arrivals_view_products = db.relationship(
        "ArrivalsViewProduct",
        backref="view",
        cascade="all, delete-orphan",
    )

    products = association_proxy("arrivals_view_products", "product")

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()


class ArrivalsViewProduct(BaseModel):
    __table_name__ = "arrivals_view_product"
    __export_data__ = False  # Exported by ArrivalsView

    view_id = db.Column(db.Integer, db.ForeignKey(ArrivalsView.id), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey(Product.id), primary_key=True)

    def __init__(self, view, product):
        self.view = view
        self.product = product

    def __repr__(self):
        return "<ArrivalsViewProduct: view {}, product {}>".format(
            self.view_id, self.product_id
        )
