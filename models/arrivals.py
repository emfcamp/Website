from sqlalchemy import ForeignKey
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from main import db
from models.permission import Permission

from . import BaseModel
from .product import Product

__all__ = [
    "ArrivalsView",
    "ArrivalsViewProduct",
]


class ArrivalsView(BaseModel):
    """An analog to a ProductView, except for checking in items rather than selling them."""

    __tablename__ = "arrivals_view"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True)

    required_permission_id: Mapped[int] = mapped_column(
        ForeignKey("permission.id"),
        index=True,
    )
    required_permission: Mapped[Permission] = relationship()

    arrivals_view_products: Mapped[list["ArrivalsViewProduct"]] = relationship(
        "ArrivalsViewProduct",
        back_populates="view",
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
    __tablename__ = "arrivals_view_product"
    __export_data__ = False  # Exported by ArrivalsView

    view_id: Mapped[int] = mapped_column(ForeignKey(ArrivalsView.id), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey(Product.id), primary_key=True)

    view: Mapped[ArrivalsView] = relationship(back_populates="arrivals_view_products")
    product: Mapped[Product] = relationship(back_populates="arrivals_view_products")

    def __init__(self, view, product):
        self.view = view
        self.product = product

    def __repr__(self):
        return f"<ArrivalsViewProduct: view {self.view_id}, product {self.product_id}>"
