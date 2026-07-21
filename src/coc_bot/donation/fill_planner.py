"""Budget-aware donation fill planning."""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from coc_bot.config import DonationLimits
from coc_bot.donation.capacity_parser import RequestCapacity
from coc_bot.donation.inventory import InventorySlot
from coc_bot.game_data import load_units


@dataclass
class PlannedTap:
    unit_id: str
    center: tuple[int, int]
    category: str  # troop, spell, siege
    cost: int  # housing for troop/spell, 1 for siege


@dataclass
class FillPlan:
    taps: list[PlannedTap] = field(default_factory=list)
    troop_budget: int = 0
    spell_budget: int = 0
    siege_budget: int = 0

    @property
    def empty(self) -> bool:
        return not self.taps


class FillPlanner:
    """Compute tap plan from request capacity, clan perk limits, and identified slots."""

    def __init__(self) -> None:
        self.units = load_units()

    def initial_budgets(
        self,
        capacity: RequestCapacity | None,
        donor_limits: DonationLimits,
    ) -> tuple[int, int, int]:
        if capacity is None:
            # Without OCR, fall back to clan perk caps only.
            return donor_limits.troop_housing, donor_limits.spell_housing, donor_limits.siege_count
        troop = min(capacity.troop_remaining, donor_limits.troop_housing)
        spell = min(capacity.spell_remaining, donor_limits.spell_housing)
        siege = min(capacity.siege_remaining, donor_limits.siege_count)
        return troop, spell, siege

    def plan(
        self,
        slots: list[InventorySlot],
        *,
        capacity: RequestCapacity | None,
        donor_limits: DonationLimits,
        troop_budget: int | None = None,
        spell_budget: int | None = None,
        siege_budget: int | None = None,
    ) -> FillPlan:
        """
        Greedy fill: prefer largest housing that still fits (troops/spells).
        Siege costs 1 count each. Unknown synthetic slot IDs are skipped for open fill
        (cannot debit housing safely).
        """
        if troop_budget is None or spell_budget is None or siege_budget is None:
            troop_budget, spell_budget, siege_budget = self.initial_budgets(capacity, donor_limits)

        plan = FillPlan(
            troop_budget=troop_budget,
            spell_budget=spell_budget,
            siege_budget=siege_budget,
        )

        # Separate by budget category.
        troops: list[tuple[InventorySlot, int]] = []
        spells: list[tuple[InventorySlot, int]] = []
        sieges: list[InventorySlot] = []

        for slot in slots:
            category = slot.category
            stats = self.units.get(slot.unit_id)
            if stats is not None:
                category = stats.category
            if category == "siege":
                sieges.append(slot)
                continue
            if slot.unit_id.startswith(("troop_slot_", "spell_slot_")):
                # Unidentified — cannot plan housing safely.
                continue
            housing = stats.housing if stats is not None else None
            if housing is None:
                continue
            if category == "spell":
                spells.append((slot, housing))
            else:
                troops.append((slot, housing))

        # Largest-first greedy for troops and spells.
        troops.sort(key=lambda item: item[1], reverse=True)
        spells.sort(key=lambda item: item[1], reverse=True)

        for slot, housing in troops:
            if housing <= plan.troop_budget:
                plan.taps.append(
                    PlannedTap(
                        unit_id=slot.unit_id,
                        center=slot.center,
                        category="troop",
                        cost=housing,
                    )
                )
                plan.troop_budget -= housing

        for slot in sieges:
            if plan.siege_budget <= 0:
                break
            plan.taps.append(
                PlannedTap(
                    unit_id=slot.unit_id,
                    center=slot.center,
                    category="siege",
                    cost=1,
                )
            )
            plan.siege_budget -= 1

        for slot, housing in spells:
            if housing <= plan.spell_budget:
                plan.taps.append(
                    PlannedTap(
                        unit_id=slot.unit_id,
                        center=slot.center,
                        category="spell",
                        cost=housing,
                    )
                )
                plan.spell_budget -= housing

        logger.debug(
            "Fill plan: {} taps (remaining troop={} spell={} siege={})",
            len(plan.taps),
            plan.troop_budget,
            plan.spell_budget,
            plan.siege_budget,
        )
        return plan

    def deduct_specific_slots(
        self,
        slots: list[InventorySlot],
        troop_budget: int,
        spell_budget: int,
        siege_budget: int,
    ) -> tuple[int, int, int]:
        """Reduce budgets after Phase 1 specific colored-slot donations."""
        for slot in slots:
            stats = self.units.get(slot.unit_id)
            category = stats.category if stats is not None else slot.category
            qty = max(1, slot.quantity)
            if category == "siege":
                siege_budget = max(0, siege_budget - qty)
            elif category == "spell":
                cost = (stats.housing if stats is not None else 1) * qty
                spell_budget = max(0, spell_budget - cost)
            else:
                cost = (stats.housing if stats is not None else 1) * qty
                troop_budget = max(0, troop_budget - cost)
        return troop_budget, spell_budget, siege_budget
