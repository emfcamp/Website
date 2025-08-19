from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import selectinload

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

    @classmethod
    def get_export_data(cls):
        data = {}
        query = db.select(ArrivalsView).options(selectinload(ArrivalsView.required_permission))
        for view in db.session.scalars(query):
            data[view.name] = {
                "name": view.name,
                "permission": view.required_permission.name,
                "products": [p.name for p in view.products],
            }
        return {"private": data}


class ArrivalsViewProduct(BaseModel):
    __table_name__ = "arrivals_view_product"
    __export_data__ = False  # Exported by ArrivalsView

    view_id = db.Column(db.Integer, db.ForeignKey(ArrivalsView.id), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey(Product.id), primary_key=True)

    def __init__(self, view, product):
        self.view = view
        self.product = product

    def __repr__(self):
        return f"<ArrivalsViewProduct: view {self.view_id}, product {self.product_id}>"
