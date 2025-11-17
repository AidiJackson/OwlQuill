"""Discovery and search schemas."""
from typing import Optional, Literal, Union, List
from pydantic import BaseModel

from app.schemas.profile import UserSummary, CharacterSummary, RealmSummary


class UserSearchResult(UserSummary):
    """User search result."""
    bio: Optional[str] = None
    result_type: Literal["user"] = "user"


class CharacterSearchResult(CharacterSummary):
    """Character search result."""
    short_bio: Optional[str] = None
    owner_username: Optional[str] = None
    result_type: Literal["character"] = "character"

    model_config = {"from_attributes": True}


class RealmSearchResult(RealmSummary):
    """Realm search result."""
    description: Optional[str] = None
    owner_username: Optional[str] = None
    is_public: bool = True
    result_type: Literal["realm"] = "realm"

    model_config = {"from_attributes": True}


SearchResult = Union[UserSearchResult, CharacterSearchResult, RealmSearchResult]


class SearchResponse(BaseModel):
    """Search response containing all result types."""
    results: List[SearchResult]
    total: int
