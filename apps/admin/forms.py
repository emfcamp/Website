from wtforms.validators import (
    Optional,
    DataRequired,
    InputRequired,
    ValidationError,
)
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField,
    StringField,
    SelectField,
    DateField,
    IntegerField,
    DecimalField,
    FieldList,
    FormField,
    HiddenField,
    BooleanField,
)

from models.product import ProductGroup
from models.basket import Basket

from ..common import CURRENCY_SYMBOLS
from ..common.forms import (
    Form,
    IntegerSelectField,
    HiddenIntegerField,
    JSONField,
    EmailField,
)


class ProductForm(Form):
    name = StringField("Internal Name")
    display_name = StringField("Display Name")
    capacity_max = IntegerField("Maximum to sell (Optional)", [Optional()])
    expires = DateField("Expiry Date (Optional)", [Optional()])
    description = StringField("Description", [Optional()], widget=TextArea())
    attributes = JSONField("Attributes")

    def init_with_product(self, product):
        self.display_name.data = product.display_name
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.expires.data = product.expires
        self.description.data = product.description
        self.attributes.data = product.attributes

    def update_product(self, product):
        product.display_name = self.display_name.data
        product.name = self.name.data
        product.capacity_max = self.capacity_max.data
        product.expires = self.expires.data
        product.description = self.description.data
        product.attributes = self.attributes.data


class NewProductForm(ProductForm):
    submit = SubmitField("Create")


class EditProductForm(ProductForm):
    submit = SubmitField("Save")


class ProductGroupSelectField(SelectField):
    def __init__(self, name):
        groups = ProductGroup.query.all()
        options = [(group.id, group.name) for group in groups]
        super().__init__(name, options)


class ProductGroupReparentForm(Form):
    parent = ProductGroupSelectField("New parent")
    submit = SubmitField("Submit")


class ProductGroupForm(Form):
    name = StringField("Name")
    type = StringField("Type")
    capacity_max = IntegerField("Maximum to sell (Optional)", [Optional()])
    expires = DateField("Expiry Date (Optional)", [Optional()])


class NewProductGroupForm(ProductGroupForm):
    submit = SubmitField("Create")


class EditProductGroupForm(ProductGroupForm):
    submit = SubmitField("Save")

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


class CopyProductGroupForm(ProductGroupForm):
    copy = SubmitField("Copy")
    capacity_max_required = IntegerField("Maximum to sell", [InputRequired()])
    include_inactive = BooleanField("Include inactive price tiers")


class PriceTierForm(Form):
    name = StringField("Name")
    personal_limit = IntegerField("Personal maximum")


class NewPriceTierForm(PriceTierForm):
    create = SubmitField("Create", [DataRequired()])
    price_gbp = DecimalField("Price (GBP)")
    price_eur = DecimalField("Price (EUR)")


class EditPriceTierForm(PriceTierForm):
    update = SubmitField("Update", [DataRequired()])


class ModifyPriceTierForm(Form):
    delete = SubmitField("Delete")
    activate = SubmitField("Activate")
    deactivate = SubmitField("Deactivate")


class ProductViewProductForm(Form):
    order = IntegerField("Order", [InputRequired()])
    product_id = HiddenIntegerField("product_id", [InputRequired()])
    delete = SubmitField("Delete")


class ProductViewForm(Form):
    name = StringField("Name")
    type = StringField("Type", default="tickets")
    cfp_accepted_only = BooleanField("Accepted CfP proposal required")


class NewProductViewForm(ProductViewForm):
    create = SubmitField("Create", [DataRequired()])


class EditProductViewForm(ProductViewForm):
    update = SubmitField("Update")
    pvps = FieldList(FormField(ProductViewProductForm))


class AddProductViewProductForm(Form):
    add_all_products = SubmitField("Add all")
    add_product = SubmitField("Add product")


class NewVoucherForm(Form):
    token = StringField("Token", [Optional()])  # Maybe auto-generated
    # expires = DateField("Expiry Date (Optional)", [Optional()])
    create = SubmitField("Create")


# class BulkNewVoucherForm(Form):
#     count = IntegerField("How many")
#     expires = DateField("Expiry Date (Optional)", [Optional()])
#     create = SubmitField("Create")


#
# Forms for reserving/issuing tickets
#


class IssueTicketsInitialForm(Form):
    " Initial form to ask for email "
    email = EmailField("Email address")
    issue_free = SubmitField("Issue Free Ticket")
    reserve = SubmitField("Reserve Ticket for Payment")


class TicketAmountForm(Form):
    " Sub-form for selecting the number for a specific ticket"
    amount = IntegerSelectField("Number of tickets", [Optional()])
    tier_id = HiddenIntegerField("Price tier", [DataRequired()])


class IssueTicketsForm(Form):
    price_tiers = FieldList(FormField(TicketAmountForm))
    allocate = SubmitField("Allocate tickets")
    currency = HiddenField("Currency", default="GBP")

    def validate_price_tiers(self, field):
        if not any(f.amount.data for f in field):
            raise ValidationError("Please choose some tickets to issue")

    def add_price_tiers(self, tiers):
        if len(self.price_tiers) == 0:
            # Only add new options if we don't have any already
            for pt in tiers:
                self.price_tiers.append_entry()
                self.price_tiers[-1].tier_id.data = pt.id

        pts = {pt.id: pt for pt in tiers}
        for f in self.price_tiers:
            f._tier = pts[f.tier_id.data]
            values = range(f._tier.personal_limit + 1)
            f.amount.values = values
            f._any = any(values)

    def create_basket(self, user):
        basket = Basket(user, self.currency.data or "GBP")
        for f in self.price_tiers:
            if f.amount.data:
                basket[f._tier] = f.amount.data
        return basket


class ReserveTicketsForm(IssueTicketsForm):
    currency = SelectField(
        "Currency", choices=[(None, "")] + list(CURRENCY_SYMBOLS.items()), default="GBP"
    )


class ReserveTicketsNewUserForm(ReserveTicketsForm):
    name = StringField("Name")


class IssueFreeTicketsNewUserForm(IssueTicketsForm):
    name = StringField("Name")


class CancelTicketForm(Form):
    cancel = SubmitField("Cancel ticket")


class ConvertTicketForm(Form):
    convert = SubmitField("Convert ticket")


class TransferTicketInitialForm(Form):
    email = EmailField("Email")
    transfer = SubmitField("Choose user")


class TransferTicketForm(Form):
    transfer = SubmitField("Transfer ticket")


class TransferTicketNewUserForm(TransferTicketForm):
    name = StringField("Name")
