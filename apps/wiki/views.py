import difflib

from flask import abort, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from sqlalchemy_continuum.utils import version_class

from main import db
from models import naive_utcnow
from models.wiki import WikiPage

from ..common import render_untrusted_markdown, require_permission
from . import wiki
from .forms import CreateWikiPageForm, WikiPageForm


def _current_version_token(page: WikiPage) -> str:
    """Return a string token representing the page's current version.

    Used for optimistic-concurrency conflict detection. The token is the
    latest transaction_id, or "0" for a page that has never been saved.
    """
    versions = list(
        page.versions.order_by(None).order_by(version_class(WikiPage).transaction_id.desc()).limit(1)  # type: ignore[attr-defined]
    )
    if versions:
        return str(versions[0].transaction_id)
    return "0"


@wiki.route("/")
def list_pages() -> ResponseReturnValue:
    pages = WikiPage.all_pages()
    return render_template("wiki/list.html", pages=pages)


@wiki.route("/new", methods=["GET", "POST"])
@require_permission("wiki")
def new_page() -> ResponseReturnValue:
    form = CreateWikiPageForm()
    if form.validate_on_submit():
        page = WikiPage(
            slug=form.slug.data,
            title=form.title.data,
            content=form.content.data or "",
            created_by_id=current_user.id,
            updated_by_id=current_user.id,
        )
        db.session.add(page)
        db.session.commit()
        flash(f"Page '{page.title}' created.")
        return redirect(url_for(".view", slug=page.slug))
    return render_template("wiki/edit.html", form=form, page=None, creating=True)


@wiki.route("/<slug>")
def view(slug: str) -> ResponseReturnValue:
    page = WikiPage.get_by_slug(slug)
    if page is None:
        abort(404)
    content_html = render_untrusted_markdown(page.content) if page.content else None
    return render_template("wiki/view.html", page=page, content_html=content_html)


@wiki.route("/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit(slug: str) -> ResponseReturnValue:
    page = WikiPage.get_by_slug(slug)
    if page is None:
        abort(404)

    form = WikiPageForm()

    if request.method == "GET":
        form.title.data = page.title
        form.content.data = page.content
        form.version_token.data = _current_version_token(page)
        return render_template("wiki/edit.html", form=form, page=page, creating=False)

    if not form.validate_on_submit():
        return render_template("wiki/edit.html", form=form, page=page, creating=False)

    # Conflict detection: compare stored token against current state
    saved_token = form.version_token.data or "0"
    current_token = _current_version_token(page)
    force = request.form.get("force") == "1"

    if saved_token != current_token and not force:
        # Someone else saved between when this user opened the edit form
        # and now. Show the diff so the user can decide.
        conflict_diff = list(
            difflib.unified_diff(
                page.content.splitlines(keepends=True),
                (form.content.data or "").splitlines(keepends=True),
                fromfile="current version",
                tofile="your edit",
                lineterm="",
            )
        )
        return render_template(
            "wiki/edit.html",
            form=form,
            page=page,
            creating=False,
            conflict=True,
            conflict_diff=conflict_diff,
        )

    assert form.title.data is not None
    page.title = form.title.data
    page.content = form.content.data or ""
    page.updated_by_id = current_user.id
    page.updated_at = naive_utcnow()
    db.session.commit()

    flash("Page saved.")
    return redirect(url_for(".view", slug=slug))


@wiki.route("/<slug>/history")
def history(slug: str) -> ResponseReturnValue:
    page = WikiPage.get_by_slug(slug)
    if page is None:
        abort(404)

    WikiPageVersion = version_class(WikiPage)
    versions = list(page.versions.order_by(None).order_by(WikiPageVersion.transaction_id.desc()))  # type: ignore[attr-defined]
    return render_template("wiki/history.html", page=page, versions=versions)


@wiki.route("/<slug>/diff/<int:from_txn>/<int:to_txn>")
def diff(slug: str, from_txn: int, to_txn: int) -> ResponseReturnValue:
    page = WikiPage.get_by_slug(slug)
    if page is None:
        abort(404)

    WikiPageVersion = version_class(WikiPage)
    from_ver = page.versions.filter(WikiPageVersion.transaction_id == from_txn).first()  # type: ignore[attr-defined]
    to_ver = page.versions.filter(WikiPageVersion.transaction_id == to_txn).first()  # type: ignore[attr-defined]

    if from_ver is None or to_ver is None:
        abort(404)

    from_lines = (from_ver.content or "").splitlines(keepends=True)
    to_lines = (to_ver.content or "").splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=f"Version #{from_txn}  ({from_ver.transaction.issued_at.strftime('%Y-%m-%d %H:%M')})",
            tofile=f"Version #{to_txn}  ({to_ver.transaction.issued_at.strftime('%Y-%m-%d %H:%M')})",
            lineterm="",
        )
    )

    return render_template(
        "wiki/diff.html",
        page=page,
        diff_lines=diff_lines,
        from_txn=from_txn,
        to_txn=to_txn,
        from_ver=from_ver,
        to_ver=to_ver,
    )
