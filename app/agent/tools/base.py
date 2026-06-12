from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel
from langchain_core.tools import BaseTool, StructuredTool


class BaseAgentTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[type[BaseModel] | None] = None

    def as_langchain_tool(self) -> BaseTool:
        return StructuredTool.from_function(
            func=self.execute,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        raise NotImplementedError
