from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict


def serialize_event(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return message_to_dict(value)
    if isinstance(value, dict):
        return {key: serialize_event(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_event(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_event(item) for item in value]
    return value


def message_content_to_text(content: Any) -> str:
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
