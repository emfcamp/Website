import sys
from pathlib import Path

sys.path.insert(0, str(Path("..").resolve()))

project = "EMF Website"
copyright = "Electromagnetic Field Ltd & contributors"
author = "EMF Web Team"

extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.linkcode", "sphinx_autodoc_typehints"]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
autodoc_member_order = "bysource"


def linkcode_resolve(domain, info):
    if domain != "py":
        return None
    if not info["module"]:
        return None
    filename = info["module"].replace(".", "/")
    return f"https://github.com/emfcamp/Website/tree/main/{filename}.py"
