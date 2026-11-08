"""Who may see what. The single source of truth for permissions.

Every tool receives the `Principal` built from the signed session token. Identity, role and
account scope come only from there; arguments chosen by the model are treated as requests
that these checks accept or refuse. This is what keeps access correct even if the model is
fully jailbroken.
"""
import re
import unicodedata
from dataclasses import dataclass

from .data import Dataset

# Role -> permissions.
#   internal:   staff tool access, all accounts visible (row-level scope)
#   staff_names: may see ParcelPilot staff names (CSM, ticket assignee)
#   personal:   may see customer personal data (emails, phones, addresses, contact names)
#   commercial: may see contract commercial terms (fees, credits, caps, discounts, pricing)
ROLES = {
    "customer_user":  dict(internal=False, staff_names=False, personal=False, commercial=True),
    "customer_admin": dict(internal=False, staff_names=True,  personal=True,  commercial=True),
    "support_l1":     dict(internal=True,  staff_names=True,  personal=False, commercial=False),
    "support_l2":     dict(internal=True,  staff_names=True,  personal=True,  commercial=True),
    "ops_manager":    dict(internal=True,  staff_names=True,  personal=True,  commercial=True),
}
INTERNAL_ROLES = {r for r, p in ROLES.items() if p["internal"]}
ALL_ROLES = set(ROLES)

# Field-level rules, matched against column names so new columns are covered too.
STAFF_COLUMNS = re.compile(r"^(csm|assigned_to|owner|agent|assignee)$")
PERSONAL_COLUMNS = re.compile(r"(email|phone|mobile|address|contact|person|^name$|first_name|last_name)")
INTERNAL_ONLY_COLUMNS = {"accounts": {"notes"}}  # internal account notes are never shown to customers

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+\d[\d\s-]{7,}\d|\b\d{5}[\s-]?\d{5}\b|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b")
MASK = "[masked]"
RESTRICTED = "[restricted: contract commercial terms are not visible to your role]"


class AccessDenied(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    role: str
    account_id: str | None

    def can(self, permission: str) -> bool:
        return ROLES[self.role][permission]

    @property
    def internal(self) -> bool:
        return self.can("internal")


def visible_account_ids(principal: Principal, dataset: Dataset) -> set[str]:
    if principal.internal:
        return {a["account_id"] for a in dataset.rows("accounts")}
    return {principal.account_id} if principal.account_id else set()


def id_key(value) -> str:
    """An id or name as compared: models often write ids with a Unicode hyphen (ABC‑123 with U+2011) or odd spacing."""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", re.sub(r"[‐-―−]", "-", text)).strip().lower()


def resolve_account(principal: Principal, dataset: Dataset, ref: str | None) -> dict:
    """Account row for an ID or name the model supplied. Customers only ever get their own."""
    if not ref:
        ref = principal.account_id
        if not ref:
            raise ValueError("Specify which account (ID or name).")
    needle = id_key(ref)
    match = next(
        (a for a in dataset.rows("accounts")
         if needle == id_key(a["account_id"]) or needle in id_key(a.get("account_name", ""))),
        None,
    )
    if match is None or match["account_id"] not in visible_account_ids(principal, dataset):
        if not principal.internal:
            raise AccessDenied("That account is not found or not accessible from your login.")
        raise LookupError(f"No account matches {ref!r}.")
    return match


def check_row(principal: Principal, dataset: Dataset, row: dict) -> None:
    if row.get("account_id") not in visible_account_ids(principal, dataset):
        raise AccessDenied("That record is not found or not accessible from your login.")


def staff_names(dataset: Dataset) -> set[str]:
    return {
        str(v) for rows in dataset.tables.values() for r in rows for k, v in r.items()
        if v and STAFF_COLUMNS.search(k)
    }


def scrub_text(principal: Principal, text: str, names: set[str]) -> str:
    if not principal.can("personal"):
        text = _PHONE.sub(MASK, _EMAIL.sub(MASK, text))
    if not principal.can("staff_names"):
        for name in sorted(names, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(name)}\b", MASK, text)
    return text


def mask_row(principal: Principal, table: str, row: dict, names: set[str]) -> dict:
    out = {}
    for key, value in row.items():
        if not principal.internal and key in INTERNAL_ONLY_COLUMNS.get(table, set()):
            continue
        if value is not None and STAFF_COLUMNS.search(key) and not principal.can("staff_names"):
            value = MASK
        elif value is not None and PERSONAL_COLUMNS.search(key) and not principal.can("personal"):
            value = MASK
        elif isinstance(value, str):
            value = scrub_text(principal, value, names)
        out[key] = value
    return out
