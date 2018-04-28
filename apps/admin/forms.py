from wtforms.validators import Optional
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField, SelectField,
    DateField, IntegerField, DecimalField,
)

from models.product import ProductGroup

from ..common.forms import Form, StaticField


class EditProductForm(Form):
    name = StringField('Name')
    capacity_max = IntegerField('Maximum to sell')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    personal_limit = IntegerField('Maximum to sell to an individual')
    price_gbp = StaticField('Price (GBP)')
    price_eur = StaticField('Price (EUR)')
    badge = BooleanField('Issue Badge')
    transferable = BooleanField('Transferable')
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Save')

    def init_with_product(self, product):
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.expires.data = product.expires
        self.personal_limit.data = product.get_price_tier('standard').personal_limit
        self.price_gbp.data = product.get_price_tier('standard').get_price('GBP')
        self.price_eur.data = product.get_price_tier('standard').get_price('EUR')
        self.badge.data = product.get_attribute('badge')
        self.transferable.data = product.get_attribute('transferable')
        self.description.data = product.description


class NewProductForm(Form):
    name = StringField('Name')
    capacity_max = IntegerField('Maximum to sell')
    personal_limit = IntegerField('Maximum to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = DecimalField('Price (GBP)')
    price_eur = DecimalField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Create')

    def init_with_product(self, product):
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.personal_limit.data = product.personal_limit
        self.expires.data = product.expires
        self.has_badge.data = product.has_badge
        self.is_transferable.data = product.is_transferable
        self.price_gbp.data = product.get_price('GBP')
        self.price_eur.data = product.get_price('EUR')
        self.description.data = product.description


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

