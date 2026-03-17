from functools import total_ordering


@total_ordering
class UnlimitedType:
    """A value that sorts higher than all ints"""

    def __eq__(self, other):
        return isinstance(other, UnlimitedType)

    def __gt__(self, other):
        if isinstance(other, UnlimitedType):
            return False
        return True

    def __lt__(self, other):
        return False

    def __repr__(self):
        return "<Unlimited>"


Unlimited = UnlimitedType()
