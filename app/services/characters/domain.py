MAX_CHARACTER_SLOTS = 30
FREE_CHARACTER_SLOTS = 3
PAID_CHARACTER_CREDIT_COST = 2


def generation_credit_cost(mode: str, slot_number: int) -> int:
    if mode == "edit":
        return PAID_CHARACTER_CREDIT_COST
    return 0 if slot_number <= FREE_CHARACTER_SLOTS else PAID_CHARACTER_CREDIT_COST


def lowest_free_slot(occupied_slots: list[int], reserved_slots: list[int]) -> int | None:
    unavailable = set(occupied_slots) | set(reserved_slots)
    for slot_number in range(1, MAX_CHARACTER_SLOTS + 1):
        if slot_number not in unavailable:
            return slot_number
    return None


def quote_version_for_revision(revision: int) -> str:
    return str(max(0, int(revision)))
