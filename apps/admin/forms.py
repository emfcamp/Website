from wtforms.validators import Optional
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, StringField, SelectField,
    DateField, IntegerField, DecimalField,
)

from models.product import ProductGroup

from ..common.forms import Form


class ProductForm(Form):
    name = StringField('Internal Name')
    display_name = StringField('Display Name')
    capacity_max = IntegerField('Maximum to sell (Optional)', [Optional()])
    expires = DateField('Expiry Date (Optional)', [Optional()])
    description = StringField('Description', [Optional()], widget=TextArea())

    def init_with_product(self, product):
        self.display_name.data = product.display_name
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.expires.data = product.expires
        self.description.data = product.description

    def update_product(self, product):
        product.display_name = self.display_name.data
        product.name = self.name.data
        product.capacity_max = self.capacity_max.data
        product.expires = self.expires.data
        product.description = self.description.data


class NewProductForm(ProductForm):
    submit = SubmitField('Create')


class EditProductForm(ProductForm):
    submit = SubmitField('Save')


class ProductGroupSelectField(SelectField):
    def __init__(self, name):
        groups = ProductGroup.query.all()
        options = [(group.id, group.name) for group in groups]
        super().__init__(name, options)


class ProductGroupReparentForm(Form):
    parent = ProductGroupSelectField("New parent")
    submit = SubmitField('Submit')


class ProductGroupForm(Form):
    name = StringField('Name')
    type = StringField('Type')
    capacity_max = IntegerField('Maximum to sell (Optional)', [Optional()])
    expires = DateField('Expiry Date (Optional)', [Optional()])


class NewProductGroupForm(ProductGroupForm):
    submit = SubmitField('Create')


class EditProductGroupForm(ProductGroupForm):
    submit = SubmitField('Save')

    def init_with_pg(self, pg):
        self.name.data = pg.name
        self.type.data = pg.type
        self.capacity_max.data = pg.capacity_max
        self.expires.data = pg.expires

    def update_pg(self, pg):
        pg.name = self.name.data
        pg.type = self.type.data
        pg.capacity_max = self.capacity_max.data
        pg.expires = self.expires.data
        return pg

class PriceTierForm(Form):
    name = StringField('Name')
    price_gbp = DecimalField('Price (GBP)')
    price_eur = DecimalField('Price (EUR)')
    submit = SubmitField('Submit')
