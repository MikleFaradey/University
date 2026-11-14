from dataclasses import dataclass
from typing import Protocol
from .registry import Registry
from .events import EventBus
from .cli import CommandRegistry

@dataclass
class ModuleContext:
    registry: Registry
    events: EventBus
    commands: CommandRegistry
    config: dict

class BankModule(Protocol):
    name: str

    def initialize(self, ctx: ModuleContext) -> None:
        ...

    def register_commands(self, commands: CommandRegistry) -> None:
        ...
