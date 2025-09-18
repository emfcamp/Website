from flask import (
    current_app as app,
)
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.dialects.postgresql import insert

from main import db, get_or_404
from models.arrivals import (
    ArrivalsView,
    ArrivalsViewProduct,
)
from models.permission import Permission
from models.product import (
    Product,
    ProductGroup,
)

from . import admin
from .forms import (
    AddArrivalsViewProductForm,
    EditArrivalsViewForm,
    NewArrivalsViewForm,
)


@admin.route("/arrivals/views")
def arrivals_views():
    view_counts = (
        ArrivalsView.query.outerjoin(ArrivalsView.arrivals_view_products)
        .outerjoin(ArrivalsView.required_permission)
        .with_entities(ArrivalsView, db.func.count(ArrivalsViewProduct.view_id), Permission.name)
        .group_by(ArrivalsView, Permission.name)
        .order_by(ArrivalsView.id)
        .all()
    )
    return render_template("admin/arrivals/views.html", view_counts=view_counts)


@admin.route("/arrivals/views/new", methods=["GET", "POST"])
def arrivals_view_new():
    form = NewArrivalsViewForm()

    if form.validate_on_submit():
        view = ArrivalsView(
            name=form.name.data,
            required_permission_id=form.required_permission.data.id,
        )
        app.logger.info("Adding new ArrivalsView %s", view.name)
        db.session.add(view)
        db.session.commit()
        flash("ArrivalsView created")
        return redirect(url_for(".arrivals_view", view_id=view.id))

    return render_template("admin/arrivals/view-new.html", form=form)


@admin.route("/arrivals/views/<int:view_id>", methods=["GET", "POST"])
def arrivals_view(view_id):
    view = get_or_404(db, ArrivalsView, view_id)

    form = EditArrivalsViewForm(obj=view)
    if request.method != "POST":
        # Empty form - populate avps
        for avp in view.arrivals_view_products:
            form.avps.append_entry()
            f = form.avps[-1]
            f.product_id.data = avp.product_id

    avp_dict = {avp.product_id: avp for avp in view.arrivals_view_products}
    for f in form.avps:
        avp = avp_dict[f.product_id.data]
        avp._field = f

    if form.validate_on_submit():
        if form.update.data:
            view.name = form.name.data
            view.required_permission = form.required_permission.data

        elif form.delete.data:
            app.logger.info("Deleting ArrivalsView %s", view.name)
            db.session.delete(view)
            db.session.commit()
            flash(f"ArrivalsView {view.name} deleted")
            return redirect(url_for(".arrivals_views"))

        else:
            for f in form.avps:
                if f.delete.data:
                    avp = avp_dict[f.product_id.data]
                    flash(f"Removed {avp.product.display_name} ({avp.product.name}) from {view.name}")
                    db.session.delete(avp)

        db.session.commit()

    return render_template("admin/arrivals/view-edit.html", view=view, form=form)


@admin.route("/arrivals/views/<int:view_id>/add", methods=["GET", "POST"])
@admin.route("/arrivals/views/<int:view_id>/add/<int:group_id>", methods=["GET", "POST"])
@admin.route(
    "/arrivals/views/<int:view_id>/add/<int:group_id>/<int:product_id>",
    methods=["GET", "POST"],
)
def arrivals_view_add(view_id, group_id=None, product_id=None):
    view = get_or_404(db, ArrivalsView, view_id)
    form = AddArrivalsViewProductForm()

    root_groups = ProductGroup.query.filter_by(parent_id=None).order_by(ProductGroup.id).all()

    if product_id is not None:
        product = Product.query.get(product_id)
    else:
        product = None
        del form.add_product

    if group_id is not None:
        group = ProductGroup.query.get(group_id)
    else:
        group = None
        del form.add_all_products

    if form.validate_on_submit():
        if form.add_all_products.data:
            for product in group.products:
                db.session.add(ArrivalsViewProduct(view, product))
            flash(f"Added all products under {group.name} to {view.name}")
            db.session.commit()

        elif form.add_all_products_recursive.data:

            def _fetch_all_products(group: ProductGroup) -> list[dict[str, int]]:
                out = []
                for product in group.products:
                    out.append({"view_id": view.id, "product_id": product.id})
                for child_group in group.children:
                    out.extend(_fetch_all_products(child_group))
                return out

            db.session.execute(
                insert(ArrivalsViewProduct).values(_fetch_all_products(group)).on_conflict_do_nothing()
            )
            flash(f"Added all products under {group.name} recursively to {view.name}")
            db.session.commit()

        elif form.add_product.data:
            db.session.add(ArrivalsViewProduct(view, product))
            flash(f"Added {product.display_name} ({product.name}) to {view.name}")
            db.session.commit()

        return redirect(url_for(".arrivals_view", view_id=view.id))

    return render_template(
        "admin/arrivals/view-add-products.html",
        view=view,
        form=form,
        root_groups=root_groups,
        add_group=group,
        add_product=product,
    )
