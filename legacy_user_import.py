import re
from collections import Counter, defaultdict


DISCORD_ID_PATTERN = re.compile(r"^[1-9]\d{16,19}$")


def normalize_email(value: str | None) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def plan_import(
    legacy_rows: list[tuple[str, str | None]],
    member_rows: list[tuple[int, str | None, str | None, str | None]],
) -> tuple[list[tuple[str, int, bool, bool]], Counter[str]]:
    counts: Counter[str] = Counter()
    members_by_email: dict[str, set[tuple[int, bool, bool]]] = defaultdict(set)
    owners_by_discord: dict[str, int] = {}
    discord_by_member: dict[int, str] = {}

    for member_id, discord_id, private_email, kset_email in member_rows:
        if discord_id:
            owners_by_discord[discord_id] = member_id
            discord_by_member[member_id] = discord_id
        private = normalize_email(private_email)
        kset = normalize_email(kset_email)
        if private:
            members_by_email[private].add((member_id, True, False))
        if kset:
            members_by_email[kset].add((member_id, False, True))

    candidates: list[tuple[str, int, bool, bool]] = []
    seen_discord_ids: set[str] = set()
    for raw_discord_id, raw_email in legacy_rows:
        discord_id = str(raw_discord_id)
        email = normalize_email(raw_email)
        if not DISCORD_ID_PATTERN.fullmatch(discord_id) or not email or len(email) > 254:
            counts["invalid"] += 1
            continue
        if discord_id in seen_discord_ids:
            counts["discord_conflicts"] += 1
            continue
        seen_discord_ids.add(discord_id)

        matches = members_by_email.get(email, set())
        matching_member_ids = {match[0] for match in matches}
        if not matching_member_ids:
            counts["unmatched"] += 1
            continue
        if len(matching_member_ids) != 1:
            counts["ambiguous_email"] += 1
            continue

        member_id = next(iter(matching_member_ids))
        current_discord_id = discord_by_member.get(member_id)
        if current_discord_id is not None and current_discord_id != discord_id:
            counts["discord_conflicts"] += 1
            continue
        current_owner = owners_by_discord.get(discord_id)
        if current_owner is not None and current_owner != member_id:
            counts["discord_conflicts"] += 1
            continue

        email_fields = [match for match in matches if match[0] == member_id]
        private_match = any(match[1] for match in email_fields)
        kset_match = any(match[2] for match in email_fields)
        candidates.append((discord_id, member_id, private_match, kset_match))

    candidates_per_member = Counter(candidate[1] for candidate in candidates)
    plan = []
    for candidate in candidates:
        discord_id, member_id, _, _ = candidate
        if candidates_per_member[member_id] > 1:
            counts["member_conflicts"] += 1
        elif owners_by_discord.get(discord_id) == member_id:
            counts["already_linked"] += 1
            plan.append(candidate)
        else:
            counts["would_link"] += 1
            plan.append(candidate)

    return plan, counts
