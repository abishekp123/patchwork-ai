from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    repository_id: str | None = None
    request_id: str | None = None
    details: list[ValidationIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail
