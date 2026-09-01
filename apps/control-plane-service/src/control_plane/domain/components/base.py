from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigurationComponent:
    name: str
