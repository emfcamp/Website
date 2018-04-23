
# We only want to import venue once the volunteers global
# has been initialised.
def init():
    from . import venue # noqa: F401
