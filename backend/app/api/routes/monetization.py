"""Monetization routes - pricing tiers and AI credits scaffold."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import User as UserModel

router = APIRouter()


class PlanFeature(BaseModel):
    """A feature included in a plan."""
    name: str
    included: bool
    limit: Optional[str] = None


class Plan(BaseModel):
    """Subscription plan details."""
    id: str
    name: str
    price_monthly: Optional[float]
    price_label: str
    description: str
    ai_credits_monthly: int
    features: list[PlanFeature]
    is_popular: bool = False


class PlansResponse(BaseModel):
    """Response containing all available plans."""
    plans: list[Plan]
    payments_enabled: bool
    credit_packs: list[dict]


class CreditsResponse(BaseModel):
    """User's current credit balance and plan info."""
    balance: int
    monthly_allowance: int
    plan: str


# Hardcoded plans - no database required for scaffold
PLANS = [
    Plan(
        id="free",
        name="Free",
        price_monthly=0,
        price_label="$0/month",
        description="Perfect for writers who love text-first storytelling.",
        ai_credits_monthly=0,
        features=[
            PlanFeature(name="Unlimited Characters", included=True),
            PlanFeature(name="Unlimited Realms", included=True),
            PlanFeature(name="Unlimited Scenes", included=True),
            PlanFeature(name="Unlimited Posts", included=True),
            PlanFeature(name="AI Image Credits", included=True, limit="3 lifetime trial"),
            PlanFeature(name="Community Features", included=True),
        ]
    ),
    Plan(
        id="creator",
        name="Creator",
        price_monthly=None,
        price_label="Coming Soon",
        description="For active storytellers who want AI-assisted visuals.",
        ai_credits_monthly=50,
        features=[
            PlanFeature(name="Everything in Free", included=True),
            PlanFeature(name="AI Image Credits", included=True, limit="50/month"),
            PlanFeature(name="Priority Support", included=True),
            PlanFeature(name="Early Access Features", included=True),
            PlanFeature(name="Creator Badge", included=True),
        ],
        is_popular=True
    ),
    Plan(
        id="studio",
        name="Studio",
        price_monthly=None,
        price_label="Coming Soon",
        description="For power users and collaborative creator groups.",
        ai_credits_monthly=200,
        features=[
            PlanFeature(name="Everything in Creator", included=True),
            PlanFeature(name="AI Image Credits", included=True, limit="200/month"),
            PlanFeature(name="Video Snippets", included=False, limit="Coming later"),
            PlanFeature(name="Custom Templates", included=False, limit="Coming later"),
            PlanFeature(name="Batch Generation", included=False, limit="Coming later"),
            PlanFeature(name="Studio Badge", included=True),
            PlanFeature(name="Direct Dev Feedback Channel", included=True),
        ]
    ),
]

CREDIT_PACKS = [
    {"id": "small", "name": "Small Pack", "credits": 20, "price_label": "TBD"},
    {"id": "medium", "name": "Medium Pack", "credits": 60, "price_label": "TBD"},
    {"id": "large", "name": "Large Pack", "credits": 150, "price_label": "TBD"},
]


@router.get("/plans", response_model=PlansResponse)
def get_plans() -> PlansResponse:
    """Get available subscription plans and credit packs.

    Returns plan information. Payments are not yet enabled.
    """
    return PlansResponse(
        plans=PLANS,
        payments_enabled=False,
        credit_packs=CREDIT_PACKS
    )


@router.get("/credits", response_model=CreditsResponse)
def get_credits(current_user: UserModel = Depends(get_current_user)) -> CreditsResponse:
    """Get current user's AI credit balance.

    Requires authentication. Returns mocked data for scaffold phase.
    """
    # For scaffold phase: all users are on free plan with 3 trial credits
    # In production, this would read from user profile or subscription table
    return CreditsResponse(
        balance=3,  # Free trial credits
        monthly_allowance=0,  # Free plan has no monthly allowance
        plan="free"
    )
