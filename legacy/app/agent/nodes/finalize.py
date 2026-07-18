from langchain_core.messages import AIMessage, message_to_dict

from app.agent.nodes.base import AgentNode
from app.agent.schemas.state import AgentState


class FinalizeNode(AgentNode):
    name = "finalize"

    def __call__(self, state: AgentState) -> AgentState:
        messages = list(state["messages"])
        response = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            AIMessage(content=""),
        )

        return {
            "response_text": _message_content_to_text(response.content),
            "response": message_to_dict(response),
        }


def _message_content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        return "\n".join(text_parts)
    return str(content)
