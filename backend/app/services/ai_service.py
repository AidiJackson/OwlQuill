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
        """Generate fake character bio."""
        name = request.name
        species = request.species or "mysterious being"
        tags_str = ", ".join(request.tags) if request.tags else "unknown"

        short_bio = (
            f"{name} is a {species} with a compelling presence. "
            f"Known for being {tags_str}, they navigate their world with unique flair."
        )

        long_bio = (
            f"{name} is a {species} whose story is still being written. "
            f"Their journey has been marked by {tags_str} moments that have shaped who they are today. "
            f"With a past shrouded in mystery and a future full of possibilities, {name} stands at "
            f"the crossroads of destiny. Their relationships are complex, their motivations deep, "
            f"and their impact on those around them undeniable. Every choice they make ripples "
            f"through their world, creating new paths and closing others. The tale of {name} is "
            f"one of transformation, challenge, and the eternal search for meaning in a vast universe."
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
