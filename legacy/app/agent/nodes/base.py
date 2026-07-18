from abc import ABC, abstractmethod
from typing import ClassVar

from app.agent.schemas.state import AgentState


class BaseNode(ABC):
    name: ClassVar[str]

    @abstractmethod
    def __call__(self, state: AgentState, *args, **kwargs):
        raise NotImplementedError


class AgentNode(BaseNode, ABC):
    pass


class ConditionalNode(ABC):
    name: ClassVar[str]

    @abstractmethod
    def __call__(self, state: AgentState) -> str:
        raise NotImplementedError
