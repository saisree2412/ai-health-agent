"""Pydantic v2 models — one source of truth for every boundary.

Every model defined here is used in three places:
1. As the MCP tool's input_schema (sent to the LLM).
2. As the validator on the dispatch side (raises if the model emits bad args).
3. As the typed return value the agent loop consumes.

This is the "Pydantic on every boundary" rule from Session 5.
"""

from health_agent.models.medical import (
    Profile,
    Condition,
    Medication,
    Allergy,
    Goal,
    Severity,
)
from health_agent.models.food import (
    FoodCatalogItem,
    Macros,
    MealLog,
    MealSlot,
    FOOD_TAG_VOCAB,
)
from health_agent.models.supplements import (
    Supplement,
    SupplementLog,
    SupplementType,
)
from health_agent.models.agent import (
    Suggestion,
    Question,
    ActionConfirmation,
    AgentReply,
    SafetyVerdict,
    SafetyFlag,
    FlagSeverity,
    ReasoningType,
    TraceEvent,
    AgentTrace,
)

__all__ = [
    # medical
    "Profile",
    "Condition",
    "Medication",
    "Allergy",
    "Goal",
    "Severity",
    # food
    "FoodCatalogItem",
    "Macros",
    "MealLog",
    "MealSlot",
    "FOOD_TAG_VOCAB",
    # supplements
    "Supplement",
    "SupplementLog",
    "SupplementType",
    # agent responses
    "Suggestion",
    "Question",
    "ActionConfirmation",
    "AgentReply",
    "SafetyVerdict",
    "SafetyFlag",
    "FlagSeverity",
    "ReasoningType",
    "TraceEvent",
    "AgentTrace",
]
