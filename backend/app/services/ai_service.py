"""AI service for generating content (MVP stub with fake data)."""
from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    SceneRequest,
    SceneResponse
)


class FakeAIClient:
    """Fake AI client for MVP. Replace with real AI integration later."""

    def generate_character_bio(self, request: CharacterBioRequest) -> CharacterBioResponse:
        """Generate fake character bio with enhanced RP details."""
        name = request.name
        species = request.species or "mysterious being"
        role = request.role or "wanderer"
        era = request.era or "unknown era"
        tags_str = ", ".join(request.tags) if request.tags else "enigmatic"

        short_bio = (
            f"{name} is a {species} {role} from the {era}. "
            f"Characterized by {tags_str} traits, they move through their world "
            f"with purpose and complexity."
        )

        long_bio = (
            f"{name}, a {species} {role} navigating the {era}, carries a story "
            f"woven with {tags_str} threads. Their past is marked by defining moments "
            f"that shaped their path as a {role}. In the context of the {era}, they face "
            f"challenges unique to their time and circumstance.\n\n"
            f"As a {species}, {name} possesses qualities that set them apart, while their "
            f"role as a {role} defines how they interact with the world around them. "
            f"Their relationships are layered, their motivations run deep, and every choice "
            f"they make sends ripples through their reality.\n\n"
            f"The tale of {name} is one of growth, conflict, and the search for purpose "
            f"in a world filled with both wonder and danger. Whether facing allies or "
            f"adversaries, {name} remains true to their nature as a {tags_str} {role}, "
            f"leaving an indelible mark on all they encounter."
        )

        return CharacterBioResponse(short_bio=short_bio, long_bio=long_bio)

    def generate_scene(self, request: SceneRequest) -> SceneResponse:
        """Generate fake scene."""
        characters_str = " and ".join(request.characters)
        mood = request.mood or "tense"
        setting = request.setting

        scene = (
            f"The {mood} atmosphere hung heavy in the {setting}. "
            f"{characters_str} found themselves at a pivotal moment. "
            f"The air crackled with unspoken words and possibilities. "
            f"What happens next will change everything..."
        )

        dialogue = (
            f'"{request.prompt}," one of them said, breaking the silence. '
            f"The words hung in the air between them, pregnant with meaning."
        )

        return SceneResponse(scene=scene, dialogue=dialogue)


# Singleton instance
ai_client = FakeAIClient()
