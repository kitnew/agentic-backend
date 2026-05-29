from fastapi import HTTPException
from app.backend.schemas.message import Message, MessageRequest

from app.agent.agent import agent
from app.agent.state import AgentState


def classify_message(message: MessageRequest) -> Message:
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    result = agent.invoke(
        AgentState(
            message=str(message.content),
            intent=""
        )
    )

    return Message(
        content=message.content,
        intent=result["intent"],
        status="classified"
    )