"""External-API adapters — USDA FoodData Central, etc.

Each module here is a thin async wrapper that converts an external response
into one of our Pydantic models (FoodCatalogItem, Macros). That way the rest
of the agent never sees raw external JSON.
"""
