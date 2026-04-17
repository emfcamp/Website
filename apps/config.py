from datetime import datetime
from typing import Any

from dateutil.parser import parse
from flask import Config


class ConfigNotInitialised(Exception):
    pass


class ConfigVariableNotPresent(Exception):
    pass


class EMFConfig:
    """
    Singleton object representing the EMF app config.

    This decouples our config from the Flask app object and lets us keep config utility methods in one place.
    """

    config: Config | None
    _date_cache: dict[str, datetime]

    def init(self, flask_config: Config) -> None:
        self.config = flask_config
        self._date_cache = {}

    def get(self, key: str, default: Any | None = None) -> Any:
        if not self.config:
            raise ConfigNotInitialised()
        if key in self.config:
            return self.config[key]
        if default is None:
            raise ConfigVariableNotPresent()
        return default

    def get_date(self, key: str) -> datetime:
        if key not in self._date_cache:
            self._date_cache[key] = parse(self.get(key))
        return self._date_cache[key]

    @property
    def event_start(self) -> datetime:
        return self.get_date("EVENT_START")

    @property
    def event_year(self) -> int:
        return self.event_start.year

    @property
    def event_end(self) -> datetime:
        return self.get_date("EVENT_END")

    def from_email(self, config_name: str) -> str:
        # config_name is e.g. TICKETS_EMAIL
        name, email = self.get(config_name)
        return f"{name} <{email}>"


config = EMFConfig()
