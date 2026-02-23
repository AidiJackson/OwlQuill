"""Schemas for the grammar-check endpoint."""
from typing import Optional
from pydantic import BaseModel, Field


class GrammarCheckRequest(BaseModel):
    text: str = Field(..., description="Text to check (max 20 000 chars)")
    language: Optional[str] = Field(
        None,
        description="BCP-47 language tag, e.g. 'en-US'. Defaults to 'en-US'.",
    )


class GrammarRuleSchema(BaseModel):
    id: str
    description: Optional[str] = None
    issueType: Optional[str] = None
    category: Optional[str] = None


class GrammarReplacementSchema(BaseModel):
    value: str


class GrammarMatchSchema(BaseModel):
    offset: int
    length: int
    message: str
    shortMessage: Optional[str] = None
    rule: GrammarRuleSchema
    replacements: list[GrammarReplacementSchema]


class GrammarCheckResponse(BaseModel):
    language: str
    matches: list[GrammarMatchSchema]
