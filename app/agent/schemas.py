from pydantic import BaseModel, Field


class IntentRequest(BaseModel):
    message: str = Field(..., min_length=1)


class IntentResponse(BaseModel):
    message: str
    intent: str


class IntentClassification(BaseModel):
    intent: str = Field(
        ...,
        description="Short intent name for the user's message, for example: reservation, question, complaint, greeting, other.",
    )
