import difflib

from flask import abort, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from merge3 import Merge3
from sqlalchemy_continuum.utils import version_class

from main import db
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
    WikiPageVersion = version_class(WikiPage)
    latest_versions = {
        page.id: (
            page.versions.order_by(None)  # type: ignore[attr-defined]
            .order_by(WikiPageVersion.transaction_id.desc())
            .first()
        )
        for page in pages
    }
    return render_template("wiki/list.html", pages=pages, latest_versions=latest_versions)


@wiki.route("/new", methods=["GET", "POST"])
@require_permission("wiki")
def new_page() -> ResponseReturnValue:
    form = CreateWikiPageForm()
    if form.validate_on_submit():
        page = WikiPage(
            slug=form.slug.data,
            title=form.title.data,
            content=form.content.data or "",
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
    WikiPageVersion = version_class(WikiPage)
    latest_version = (
        page.versions.order_by(None)  # type: ignore[attr-defined]
        .order_by(WikiPageVersion.transaction_id.desc())
        .first()
    )
    return render_template(
        "wiki/view.html", page=page, content_html=content_html, latest_version=latest_version
    )


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

    # Non-admins cannot change the title; fill it in so validation passes
    if not current_user.has_permission("admin"):
        form.title.data = page.title

    if not form.validate_on_submit():
        return render_template("wiki/edit.html", form=form, page=page, creating=False)

    # Conflict detection: 3-way merge against the base version the user started from
    saved_token = form.version_token.data or "0"
    current_token = _current_version_token(page)

    if saved_token != current_token:
        # Look up base content (what the user started editing from)
        WikiPageVersion = version_class(WikiPage)
        if saved_token == "0":
            base_content = ""
        else:
            base_ver = page.versions.filter(  # type: ignore[attr-defined]
                WikiPageVersion.transaction_id == int(saved_token)
            ).first()
            base_content = (base_ver.content or "") if base_ver else ""

        base_lines = base_content.splitlines(keepends=True)
        current_lines = page.content.splitlines(keepends=True)
        our_lines = (form.content.data or "").splitlines(keepends=True)

        merged_lines = list(
            Merge3(base_lines, current_lines, our_lines).merge_lines(
                name_a="current version", name_b="your edit"
            )
        )
        has_conflict = any(line.startswith("<<<<<<<") for line in merged_lines)

        if not has_conflict:
            # Clean 3-way merge — save automatically
            assert form.title.data is not None
            page.title = form.title.data
            page.content = "".join(merged_lines)
            db.session.commit()
            flash("Page saved (your changes were automatically merged with a concurrent edit).")
            return redirect(url_for(".view", slug=slug))

        # True conflict — pre-fill textarea with merged content including conflict markers
        form.content.data = "".join(merged_lines)
        form.version_token.data = current_token
        return render_template(
            "wiki/edit.html",
            form=form,
            page=page,
            creating=False,
            conflict=True,
        )

    assert form.title.data is not None
    if current_user.has_permission("admin"):
        page.title = form.title.data
    page.content = form.content.data or ""
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
