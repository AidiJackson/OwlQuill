"""Fake AI provider for development and testing."""
from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    PostSuggestionRequest,
    PostSuggestionResponse,
    SceneSummaryRequest,
    SceneSummaryResponse,
)
from app.services.ai.base import AIClient


class FakeAIProvider(AIClient):
    """Fake AI provider that returns deterministic placeholder responses.

    This provider is used for local development and testing when no real
    AI API key is configured. It returns structured, realistic-looking
    responses without making any external API calls.
    """

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

    def suggest_post_reply(self, request: PostSuggestionRequest) -> PostSuggestionResponse:
        """Generate a fake post suggestion."""
        character_name = request.character_name or "the character"
        realm_name = request.realm_name or "this realm"

        # Build context awareness
        context_note = ""
        if request.recent_posts:
            num_posts = len(request.recent_posts)
            context_note = f" (responding to {num_posts} recent post{'s' if num_posts != 1 else ''})"

        suggested_text = (
            f"[FAKE_AI_SUGGESTION{context_note}] {character_name} observes the unfolding "
            f"events in {realm_name} with keen interest. The atmosphere is charged with "
            f"possibility. They step forward, their presence commanding attention.\n\n"
            f'"The situation calls for careful consideration," they say, their voice '
            f"measured and deliberate. \"What happens next will shape the path ahead.\"\n\n"
            f"Their gaze sweeps across the scene, taking in every detail, every nuance. "
            f"This is a pivotal moment, and they know it."
        )

        if request.tone_hint:
            suggested_text += (
                f"\n\n[Tone suggestion: {request.tone_hint}] "
                f"The AI has attempted to incorporate a {request.tone_hint} tone into this response."
            )

        return PostSuggestionResponse(suggested_text=suggested_text)

    def summarize_scene(self, request: SceneSummaryRequest) -> SceneSummaryResponse:
        """Generate a fake scene summary."""
        realm_name = request.realm_name or "the realm"
        num_posts = len(request.posts) if request.posts else 0

        if num_posts == 0:
            summary = (
                f"[FAKE_AI_SUMMARY] {realm_name} awaits the first moves of its participants. "
                f"The stage is set, but the story has yet to unfold. No posts have been made yet."
            )
        elif num_posts == 1:
            summary = (
                f"[FAKE_AI_SUMMARY] {realm_name} has just begun. A single post sets the stage, "
                f"establishing the initial atmosphere and introducing the first threads of "
                f"narrative. The scene is in its opening moments, with much yet to develop."
            )
        else:
            summary = (
                f"[FAKE_AI_SUMMARY] {realm_name} is alive with activity. Across {num_posts} posts, "
                f"characters interact, tensions build, and storylines interweave. "
                f"Key themes emerge: conflict and resolution, character development, "
                f"and the exploration of relationships. The scene progresses through "
                f"dramatic moments, revelations, and pivotal choices.\n\n"
                f"Recent developments showcase the evolution of character dynamics and "
                f"the unfolding of central plot threads. The narrative momentum builds "
                f"toward significant turning points, with each post adding depth and complexity "
                f"to the overall tapestry of the story."
            )

        return SceneSummaryResponse(summary=summary)
