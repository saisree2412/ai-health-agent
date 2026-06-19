"""ProfileBuilder — assembles the cached prefix and the volatile suffix.

Why split:
    The stable prefix (user identity, conditions, meds, allergies, goals,
    supplements) is bulky and changes infrequently. It goes into the system
    message and is flagged with cache_system=True so the V2 gateway uses
    Gemini's explicit cache / OpenAI-compat's implicit prefix cache.

    The volatile suffix (today's date and the day's logs so far) changes every
    turn. It rides as a separate user-role context message *before* the actual
    user input, so it never busts the cache on the system message.
"""

from __future__ import annotations

from datetime import date
from textwrap import dedent

from health_agent.db.repos import Repos
from health_agent.models import Macros


def _age(today: date, dob: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _fmt_macros(m: Macros) -> str:
    return (
        f"{m.calories:.0f} kcal, "
        f"protein {m.protein_g:.0f} g, "
        f"carbs {m.carbs_g:.0f} g, "
        f"fat {m.fat_g:.0f} g, "
        f"fiber {m.fiber_g:.0f} g, "
        f"sugar {m.sugar_g:.0f} g, "
        f"sodium {m.sodium_mg:.0f} mg"
    )


class ProfileBuilder:
    """Two methods — call cached_prefix() once per session and volatile_suffix()
    each turn. The agent loop is responsible for wiring both into messages.
    """

    def __init__(self, repos: Repos) -> None:
        self.repos = repos

    # ── stable, cacheable ─────────────────────────────────────────────────

    def cached_prefix(self) -> str:
        r = self.repos
        p = r.profile.get()
        if p is None:
            return "=== USER PROFILE ===\n(no profile on file — ask the user to seed)\n=== END USER PROFILE ==="

        age = _age(date.today(), p.date_of_birth)

        cond_lines = []
        for c in r.conditions.list_active():
            tail = []
            if c.icd10:
                tail.append(c.icd10)
            tail.append(c.severity)
            if c.tags:
                tail.append("tags: " + ", ".join(c.tags))
            cond_lines.append(f"  - {c.name} [{'; '.join(tail)}]")

        allergy_lines = [
            f"  - {a.allergen} ({a.severity}"
            + (f", {a.reaction}" if a.reaction else "")
            + ")"
            for a in r.allergies.list_all()
        ]

        med_lines = [
            f"  - {m.name} {m.dose}{m.unit} {m.frequency}"
            + (f" — for {m.indication}" if m.indication else "")
            for m in r.medications.list_active()
        ]

        sup_lines = []
        for s in r.supplements.list_active():
            tail = f"{s.kind}, {s.typical_dose:g} {s.typical_unit}"
            if s.interaction_tags:
                tail += "; interaction tags: " + ", ".join(s.interaction_tags)
            sup_lines.append(f"  - {s.name} ({tail})")

        goal_lines = []
        for g in r.goals.list_active():
            target = ""
            if g.target_value is not None:
                target = f" → {g.target_value:g}"
                if g.target_unit:
                    target += f" {g.target_unit}"
            goal_lines.append(
                f"  - {g.kind}{target}" + (f" — {g.notes}" if g.notes else "")
            )

        def _block(label: str, lines: list[str]) -> str:
            return f"{label}:\n" + ("\n".join(lines) if lines else "  (none)")

        return dedent(
            f"""\
            === USER PROFILE (stable) ===
            Name:            {p.name}
            Age / Sex:       {age} / {p.sex}
            Height / Weight: {p.height_cm:.0f} cm / {p.weight_kg:.1f} kg
            Activity level:  {p.activity_level}
            Timezone:        {p.timezone}

            {_block("Active conditions", cond_lines)}

            {_block("Allergies / intolerances", allergy_lines)}

            {_block("Active medications", med_lines)}

            {_block("Active supplements", sup_lines)}

            {_block("Active goals", goal_lines)}
            === END USER PROFILE ===\
            """
        )

    # ── volatile, per-turn ────────────────────────────────────────────────

    def volatile_suffix(self) -> str:
        today = date.today()
        r = self.repos
        meals = r.meal_log.for_date(today)
        sups = r.supplement_log.for_date(today)
        totals = r.meal_log.sum_macros_for_date(today)

        meal_lines = [
            f"  - {m.slot} @ {m.eaten_at.strftime('%H:%M')}: "
            f"{m.servings:g}× {m.food_name} "
            f"→ {m.macros.calories:.0f} kcal, {m.macros.sodium_mg:.0f} mg Na"
            for m in meals
        ] or ["  (nothing logged yet today)"]

        sup_lines = [
            f"  - {s.taken_at.strftime('%H:%M')}: "
            f"{s.supplement_name} {s.dose:g} {s.unit}"
            for s in sups
        ] or ["  (no supplements logged yet today)"]

        return dedent(
            f"""\
            === TODAY ({today.isoformat()}) ===
            Meals so far:
            {chr(10).join(meal_lines)}

            Supplements taken today:
            {chr(10).join(sup_lines)}

            Daily macro totals so far:
              {_fmt_macros(totals)}
            === END TODAY ===\
            """
        )
