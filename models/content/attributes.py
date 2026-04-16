"""

Skeleton classes to provide typing for attributes.

These are mostly shared between Proposals and ScheduleItems,
and will be copied when the proposal is about to be finalised.
There are some extra Proposal attributes that will not be copied.

Anything entered by users probably wants to be a string or enum,
as people write things like "20-25" or "20 (space permitting)".

We allow None for strings to simplify copying from forms,
and converting to/from JSON. We include defaults to make
adding/removing fields easier, but don't account for removed fields yet.

It's possible to filter the underlying attributes_json column with
sqlalchemy, and part of why we don't use TypedDict is to avoid confusion
with that column.
"""

from dataclasses import MISSING, dataclass
from typing import Any


@dataclass
class Attributes:
    pass


# Attributes used by both Proposal and ScheduleItem


@dataclass
class TalkAttributes(Attributes):
    content_note: str | None = None
    needs_laptop: bool = False
    family_friendly: bool = False


@dataclass
class PerformanceAttributes(Attributes):
    pass


@dataclass
class WorkshopAttributes(Attributes):
    age_range: str | None = None
    participant_cost: str | None = None
    participant_equipment: str | None = None
    content_note: str | None = None
    family_friendly: bool = False


@dataclass
class YouthWorkshopAttributes(Attributes):
    age_range: str | None = None
    participant_cost: str | None = None
    participant_equipment: str | None = None
    content_note: str | None = None
    # No need for family_friendly


@dataclass
class InstallationAttributes(Attributes):
    size: str | None = None


@dataclass
class LightningTalkAttributes(Attributes):
    slide_link: str | None = None
    session: str | None = None


# Attributes only used by the review process
# These won't get copied across when creating a schedule item


@dataclass
class ProposalTalkAttributes(TalkAttributes):
    pass


@dataclass
class ProposalPerformanceAttributes(PerformanceAttributes):
    pass


@dataclass
class ProposalWorkshopAttributes(WorkshopAttributes):
    participant_count: str | None = None


@dataclass
class ProposalYouthWorkshopAttributes(YouthWorkshopAttributes):
    participant_count: str | None = None
    valid_dbs: bool | None = None


@dataclass
class ProposalInstallationAttributes(InstallationAttributes):
    grant_requested: str | None = None


# LightningTalks don't go through the review process


def attributes_proxy(attributes_cls: type[Attributes], store: dict[str, Any]) -> type[Attributes]:
    class AttributesProxy(attributes_cls):  # type: ignore[valid-type, misc]
        """Forwards dataclass fields to a backing dict, blocking access to anything not defined by the dataclass."""

        def __new__(cls, *args, **kwargs):
            obj = super().__new__(cls)
            object.__setattr__(obj, "_store", store)
            return obj

        def __getattribute__(self, name: str) -> Any:
            if name.startswith("__") or name == "_store":
                return super().__getattribute__(name)
            if name not in self.__dataclass_fields__:
                raise AttributeError(name)
            return self._store.get(name)

        def __setattr__(self, name: str, value: Any) -> None:
            if name not in self.__dataclass_fields__:
                raise AttributeError(name)
            if self._store.get(name, MISSING) != value:
                self._store[name] = value
            else:
                # MutableDict counts this as a mutation
                pass

        def __repr__(self) -> str:
            return f"<{self.__class__.__name__} {self._store!r}>"

    AttributesProxy.__name__ = f"{attributes_cls.__name__}Proxy"
    return AttributesProxy


def convert_attributes_between_types(old_attributes: Attributes, new_attributes: Attributes) -> None:
    # Logic to transfer attributes. Any not copied will be lost except in history.
    # There aren't currently many attributes that can safely be copied across.
    attributes_to_copy = [
        "family_friendly",
    ]
    if isinstance(old_attributes, WorkshopAttributes | YouthWorkshopAttributes) and isinstance(
        new_attributes, WorkshopAttributes | YouthWorkshopAttributes
    ):
        attributes_to_copy += [
            "participant_count",
            "age_range",
            "participant_cost",
            "participant_equipment",
        ]
        # family_friendly and valid_dbs can't be copied

    for a in attributes_to_copy:
        if hasattr(old_attributes, a):
            setattr(new_attributes, a, getattr(old_attributes, a))


def copy_common_attributes(old_attributes: Attributes, new_attributes: Attributes) -> None:
    for n in new_attributes.__dataclass_fields__:
        setattr(new_attributes, n, getattr(old_attributes, n))
