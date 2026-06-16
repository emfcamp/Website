from pathlib import Path
import json
import re

# Both modules use the name slugify. Prepare this script by doing:
# $ mkdir slugifies
# $ uv pip install --target slugifies/awesome_slugify awesome-slugify
# $ uv pip install --target slugifies/python_slugify python-slugify
# $ touch slugifies{,/awesome_slugify,/python_slugify}/__init__.py

from slugifies.awesome_slugify.slugify import slugify_unicode as slugify_awesome
from slugifies.python_slugify.slugify import slugify as slugify_python


def proposal_slug_awesome(title) -> str:
    slug = slugify_awesome(title).lower()
    if len(slug) > 60:
        words = re.split(" +|[,.;:!?]+", title)
        break_words = ["and", "which", "with", "without", "for", "-", ""]

        for i, word in reversed(list(enumerate(words))):
            new_slug = slugify_awesome(" ".join(words[:i])).lower()
            if word in break_words:
                if len(new_slug) > 10 and not len(new_slug) > 60:
                    slug = new_slug
                    break

            elif len(slug) > 60 and len(new_slug) > 10:
                slug = new_slug

    if len(slug) > 60:
        slug = slug[:60] + "-"

    return slug


def proposal_slug_python(title) -> str:
    replacements = [
        ["'", ""],
    ]
    slug = slugify_python(title, replacements=replacements, allow_unicode=True)
    if len(slug) > 60:
        words = re.split(" +|[,.;:!?]+", title)
        break_words = ["and", "which", "with", "without", "for", "-", ""]

        for i, word in reversed(list(enumerate(words))):
            new_slug = slugify_python(" ".join(words[:i]), replacements=replacements, allow_unicode=True)
            if word in break_words:
                if len(new_slug) > 10 and not len(new_slug) > 60:
                    slug = new_slug
                    break

            elif len(slug) > 60 and len(new_slug) > 10:
                slug = new_slug

    if len(slug) > 60:
        slug = slug[:60] + "-"

    return slug


schedules = Path("../exports").glob("*/public/schedule.json")

for schedule in schedules:
    print(f"Checking {schedule}")
    items = json.load(open(schedule))
    for item in items:
        id, title = item["id"], item["title"]
        awesome_slug = proposal_slug_awesome(title)
        python_slug = proposal_slug_python(title)

        if "slug" in item:
            slug = item["slug"]
            if awesome_slug != slug:
                print(f"Exported slug for {id} {slug!r} does not match {awesome_slug!r} ({title!r})")
                break

        if awesome_slug != python_slug:
            print(f"Slug for {id} {awesome_slug!r} does not match {python_slug!r} ({title!r})")


extra_titles = [
    "AI & Ethics 🤔",
    "C++ vs. Rust Shader Showdown",
    "Why Tabs > Spaces 🚀",
    "I rm -rf /*'d My Watch",
    "Über–かわいい (❁´◡`❁) lol",
    "i always use lowercase, it’s cool",
    "Internationalization (i18n) & Localization (l10n) In Talk Titles",
]

for title in extra_titles:
    awesome_slug = proposal_slug_awesome(title)
    python_slug = proposal_slug_python(title)

    if awesome_slug != python_slug:
        print(f"Slug {awesome_slug!r} does not match {python_slug!r} ({title!r})")
