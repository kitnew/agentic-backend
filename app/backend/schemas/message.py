from pydantic import BaseModel

class Message(BaseModel):
    content: str
    intent: str
    status: str

class MessageRequest(BaseModel):
    content: str

class MessageResponse(BaseModel):
    content: str
    intent: str