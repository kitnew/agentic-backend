from abc import ABC, abstractmethod
from typing import Any, ClassVar

from langchain_core.tools import BaseTool, StructuredTool


class BaseAgentTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]

    def as_langchain_tool(self) -> BaseTool:
        return StructuredTool.from_function(
            func=self.execute,
            name=self.name,
            description=self.description,
        )

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        raise NotImplementedError
