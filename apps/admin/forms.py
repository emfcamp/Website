from datetime import datetime, timedelta
from wtforms.validators import Optional, DataRequired, InputRequired, ValidationError
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField,
    StringField,
    SelectField,
    IntegerField,
    DecimalField,
    FieldList,
    FormField,
    HiddenField,
    BooleanField,
    TextAreaField,
)
from wtforms.fields.html5 import DateField
from wtforms_sqlalchemy.fields import QuerySelectField

from models.permission import Permission
from models.product import ProductGroup, PRODUCT_GROUP_TYPES
from models.basket import Basket

from ..common import CURRENCY_SYMBOLS
from ..common.forms import Form
from ..common.fields import (
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
    type = SelectField("Type", choices=[(t.slug, t.name) for t in PRODUCT_GROUP_TYPES])
    capacity_max = IntegerField("Maximum to sell (Optional)", [Optional()])
    expires = DateField("Expiry Date (Optional)", [Optional()])
    attributes = JSONField("Attributes")


class NewProductGroupForm(ProductGroupForm):
    submit = SubmitField("Create")


class EditProductGroupForm(ProductGroupForm):
    submit = SubmitField("Save")

    def init_with_pg(self, pg):
        self.name.data = pg.name
        self.type.data = pg.type
        self.capacity_max.data = pg.capacity_max
        self.expires.data = pg.expires
        self.attributes.data = pg.attributes

    def update_pg(self, pg):
        pg.name = self.name.data
        pg.type = self.type.data
        pg.capacity_max = self.capacity_max.data
        pg.expires = self.expires.data
        pg.attributes = self.attributes.data
        return pg


class CopyProductGroupForm(Form):
    name = StringField("Name")
    capacity_max = IntegerField("Maximum to sell (Optional)", [Optional()])
    capacity_max_required = IntegerField("Maximum to sell", [InputRequired()])
    expires = DateField("Expiry Date (Optional)", [Optional()])
    include_inactive = BooleanField("Include inactive price tiers")
    copy = SubmitField("Copy")


class PriceTierForm(Form):
    name = StringField("Name")
    personal_limit = IntegerField("Personal maximum")
    price_gbp = DecimalField("Price (GBP)")
    price_eur = DecimalField("Price (EUR)")
    vat_rate = DecimalField("VAT rate (e.g. 0.2)", [Optional()])


class NewPriceTierForm(PriceTierForm):
    create = SubmitField("Create", [DataRequired()])


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
    vouchers_only = BooleanField("Voucher required")


class NewProductViewForm(ProductViewForm):
    create = SubmitField("Create", [DataRequired()])


class EditProductViewForm(ProductViewForm):
    update = SubmitField("Update")
    pvps = FieldList(FormField(ProductViewProductForm))


class AddProductViewProductForm(Form):
    add_all_products = SubmitField("Add all")
    add_product = SubmitField("Add product")


class VoucherForm(Form):
    expires = DateField("Expiry Date", default=datetime.now() + timedelta(days=30))
    num_purchases = IntegerField("Max Purchases", [InputRequired()], default=1)
    num_tickets = IntegerField("Max Adult Tickets", [InputRequired()], default=2)


class NewVoucherForm(VoucherForm):
    voucher = StringField(
        "Voucher code (Optional)", [Optional()]
    )  # Maybe auto-generated
    create = SubmitField("Create")


class EditVoucherForm(VoucherForm):
    submit = SubmitField("Save")

    def init_with_voucher(self, voucher):
        self.expires.data = voucher.expiry
        self.num_purchases.data = voucher.purchases_remaining
        self.num_tickets.data = voucher.tickets_remaining

    def update_voucher(self, voucher):
        voucher.expiry = self.expires.data
        voucher.purchases_remaining = self.num_purchases.data
        voucher.tickets_remaining = self.num_tickets.data


class BulkVoucherEmailForm(Form):
    subject = StringField(
        "Subject", [DataRequired()], default="Your Electromagnetic Field Voucher"
    )
    text = StringField(
        "Message",
        [DataRequired()],
        widget=TextArea(),
        default="""Hello,

You can now buy your Electromagnetic Field ticket through [this link]({{voucher_url}}).

You are guaranteed these tickets until {{expiry}}, so please make sure you use your voucher before then.

Love,

Everyone at Electromagnetic Field
    """,
    )
    reason = StringField(
        "Email reason",
        [DataRequired()],
        default="You're receiving this email because you participated in a previous EMF event.",
    )
    emails = TextAreaField("Email Addresses", [DataRequired()])
    expires = DateField("Expiry Date", default=datetime.now() + timedelta(days=30))
    num_purchases = IntegerField("Max Purchases", [InputRequired()], default=1)
    num_tickets = IntegerField("Max Adult Tickets", [InputRequired()], default=2)
    preview = SubmitField("Preview")
    create = SubmitField("Send")


#
# Forms for reserving/issuing tickets
#


class IssueTicketsInitialForm(Form):
    "Initial form to ask for email"
    email = EmailField("Email address")
    issue_free = SubmitField("Issue Free Ticket")
    reserve = SubmitField("Reserve Ticket for Payment")


class TicketAmountForm(Form):
    "Sub-form for selecting the number for a specific ticket"
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
    name = StringField("Name", [InputRequired()])


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


def _available_permissions():
    return Permission.query.all()


class ArrivalsViewForm(Form):
    name = StringField("Name")
    required_permission = QuerySelectField("Required Permission", query_factory=_available_permissions, get_label='name')


class NewArrivalsViewForm(ArrivalsViewForm):
    create = SubmitField("Create", [DataRequired()])


class ArrivalsViewProductForm(Form):
    product_id = HiddenIntegerField("product_id", [InputRequired()])
    delete = SubmitField("Delete")


class EditArrivalsViewForm(ArrivalsViewForm):
    update = SubmitField("Update")
    delete = SubmitField("Delete")
    avps = FieldList(FormField(ArrivalsViewProductForm))


class AddArrivalsViewProductForm(Form):
    add_all_products = SubmitField("Add all")
    add_all_products_recursive = SubmitField("Add all (recursively)")
    add_product = SubmitField("Add product")
