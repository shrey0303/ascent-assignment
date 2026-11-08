"""Proactive issue detection for the Ops Manager dashboard. No LLM involved.

Detectors (each alert carries its method, numbers and evidence ids):
- sla_risk: open high-severity tickets (the policy's two strictest levels) breached or due within the horizon.
- complaint_spike: Poisson test of tickets in the last 24h against the account's own 30-day baseline.
- root_cause_cluster: TF-IDF cosine similarity links tickets to each other and to open known issues.
- unusual_order: rules for missed pickups and cancellation requests after pickup.
- multi_customer: the same root cause or carrier problem seen at two or more accounts.
"""
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import timedelta

from .access import Principal
from .calculator import high_severities
from .data import get_dataset
from .docs import get_library, tokens
from .tools import sla_report

SLA_HORIZON_HOURS = 4
SPIKE_WINDOW_HOURS = 24
BASELINE_DAYS = 30
BASELINE_FLOOR_PER_DAY = 0.1   # sparse history: assume at least one ticket per 10 days
SPIKE_P_VALUE = 0.01
SIMILARITY_THRESHOLD = 0.2
MISSED_PICKUP_GRACE_MINUTES = 60
_KNOWN_ISSUE = re.compile(r"^([A-Z]{2,}-\d+)\s+-\s+(.+)$")


def _alert(kind: str, severity: str, title: str, explanation: str, method: str, evidence: list[str],
           accounts: list[str], suggested_action: str) -> dict:
    key = f"{kind}|{'|'.join(sorted(evidence))}"
    return {
        "id": f"ALR-{hashlib.sha1(key.encode()).hexdigest()[:10]}", "kind": kind, "severity": severity,
        "title": title, "explanation": explanation, "method": method, "evidence": sorted(evidence),
        "accounts": sorted(set(accounts)), "suggested_action": suggested_action,
    }


def _poisson_tail(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam)."""
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))


def _account_names() -> dict[str, str]:
    return {a["account_id"]: a.get("account_name") or a["account_id"] for a in get_dataset().rows("accounts")}


def sla_alerts(principal: Principal) -> list[dict]:
    names, alerts = _account_names(), []
    for t in sla_report(principal, SLA_HORIZON_HOURS, high_severities()):
        breached = t["sla_state"] == "breached"
        minutes = abs(t["minutes_until_due"])
        alerts.append(_alert(
            "sla_risk", "critical" if breached else "warning",
            f"{t['ticket_id']} ({t['severity']}, {names.get(t['account_id'])}) "
            + (f"breached first-response SLA by {minutes} min" if breached else f"due in {minutes} min"),
            f"{t['severity']} ({t['severity_basis']}). Target {t['target']} on {t['clock']}, created {t['created_at']}, "
            f"due {t['due_at']}. Owner: {t['assigned_to']}. Target source: "
            + ", ".join(s["source_id"] for s in t["sources"]),
            "rule: calculator.ticket_sla with contract/policy precedence",
            [t["ticket_id"]], [t["account_id"]],
            "Escalate now and respond to the customer" if breached else "Make sure the owner responds before the due time",
        ))
    return alerts


def spike_alerts() -> list[dict]:
    dataset, names = get_dataset(), _account_names()
    now = dataset.snapshot
    window_start = now - timedelta(hours=SPIKE_WINDOW_HOURS)
    baseline_start = window_start - timedelta(days=BASELINE_DAYS)
    recent, baseline = defaultdict(list), Counter()
    for t in dataset.rows("tickets"):
        created = t.get("created_at")
        if not created:
            continue
        for scope in (t.get("account_id"), "ALL"):
            if window_start <= created <= now:
                recent[scope].append(t["ticket_id"])
            elif baseline_start <= created < window_start:
                baseline[scope] += 1
    alerts = []
    for scope, ids in recent.items():
        expected = max(baseline[scope] / BASELINE_DAYS, BASELINE_FLOOR_PER_DAY) * SPIKE_WINDOW_HOURS / 24
        p_value = _poisson_tail(len(ids), expected)
        if len(ids) >= 2 and p_value < SPIKE_P_VALUE:
            label = "all accounts" if scope == "ALL" else names.get(scope, scope)
            alerts.append(_alert(
                "complaint_spike", "warning", f"Complaint spike: {len(ids)} tickets in {SPIKE_WINDOW_HOURS}h ({label})",
                f"{len(ids)} tickets in the last {SPIKE_WINDOW_HOURS}h vs {baseline[scope]} in the previous "
                f"{BASELINE_DAYS} days (expected {expected:.2f} in {SPIKE_WINDOW_HOURS}h). Poisson P(X >= {len(ids)}) = "
                f"{p_value:.4f} < {SPIKE_P_VALUE}.",
                f"statistical: Poisson tail test, baseline floor {BASELINE_FLOOR_PER_DAY}/day",
                ids, [] if scope == "ALL" else [scope], "Check for a shared cause and brief the account owner",
            ))
    return alerts


def _known_issues() -> list[dict]:
    """Open known issues parsed from current product-guide sections ('<ID>-<number> - Title' blocks)."""
    issues = []
    for doc in get_library().documents.values():
        if doc.doc_type != "product_guide" or not doc.usable:
            continue
        for section in doc.sections:
            current = None
            for line in section.text.splitlines():
                match = _KNOWN_ISSUE.match(line)
                if match:
                    current = {"id": match.group(1), "title": match.group(2), "source_id": section.cite, "text": line}
                    issues.append(current)
                elif current:
                    current["text"] += " " + line
    return [i for i in issues if not re.search(r"\bresolved\b", i["text"], re.I)]


def _cosine(a: Counter, b: Counter) -> float:
    dot = sum(a[t] * b[t] for t in a.keys() & b.keys())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def cluster_alerts() -> list[dict]:
    dataset = get_dataset()
    since = dataset.snapshot - timedelta(days=BASELINE_DAYS)
    tickets = [t for t in dataset.rows("tickets") if t.get("created_at") and t["created_at"] >= since]
    issues = _known_issues()
    docs = [tokens(f"{t.get('subject') or ''} {t.get('description') or ''}") for t in tickets]
    docs += [tokens(f"{i['title']} {i['text']}") for i in issues]
    df = Counter(term for d in docs for term in set(d))
    idf = {term: math.log((1 + len(docs)) / (1 + c)) + 1 for term, c in df.items()}
    vectors = [Counter({term: n * idf[term] for term, n in Counter(d).items()}) for d in docs]
    ticket_vecs, issue_vecs = vectors[: len(tickets)], vectors[len(tickets):]

    parent = list(range(len(tickets)))  # union-find over tickets

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(tickets)):
        for j in range(i + 1, len(tickets)):
            if _cosine(ticket_vecs[i], ticket_vecs[j]) >= SIMILARITY_THRESHOLD:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(tickets)):
        groups[find(i)].append(i)

    alerts = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ids = [tickets[i]["ticket_id"] for i in members]
        accounts = [tickets[i]["account_id"] for i in members]
        best = max(((_cosine(ticket_vecs[i], issue_vecs[k]), k) for i in members for k in range(len(issues))),
                   default=(0, None))
        issue = issues[best[1]] if best[1] is not None and best[0] >= SIMILARITY_THRESHOLD else None
        shared = Counter(t for i in members for t in set(docs[i]))
        common = [t for t, c in shared.most_common() if c == len(members)][:6]
        kind = "multi_customer" if len(set(accounts)) > 1 else "root_cause_cluster"
        alerts.append(_alert(
            kind, "warning",
            f"{len(ids)} tickets share a root cause" + (f": {issue['id']} {issue['title']}" if issue else ""),
            f"Tickets {', '.join(ids)} are similar (TF-IDF cosine >= {SIMILARITY_THRESHOLD}); shared terms: "
            f"{', '.join(common)}."
            + (f" Best match to open known issue {issue['id']} (similarity {best[0]:.2f}) [{issue['source_id']}]." if issue else
               " No open known issue matches; possible new incident.")
            + (f" Affects {len(set(accounts))} accounts." if kind == "multi_customer" else ""),
            "clustering: TF-IDF cosine similarity + union-find; known-issue matching",
            ids, accounts,
            f"Link tickets to {issue['id']} and send customers the documented workaround" if issue
            else "Investigate as a possible new incident",
        ))
    return alerts


def order_alerts() -> list[dict]:
    dataset, names = get_dataset(), _account_names()
    now, alerts = dataset.snapshot, []
    missed_by_carrier = defaultdict(list)
    for o in dataset.rows("orders"):
        status = str(o.get("status") or "").upper()
        end = o.get("pickup_window_end")
        if status == "BOOKED" and not o.get("pickup_actual_at") and end and now > end:
            overdue = int((now - end).total_seconds() // 60)
            if overdue >= MISSED_PICKUP_GRACE_MINUTES:
                missed_by_carrier[o.get("carrier")].append(o)
                fault = "carrier at fault" if o.get("carrier_fault") else "fault not recorded"
                alerts.append(_alert(
                    "unusual_order", "warning",
                    f"Missed pickup: {o['order_id']} ({names.get(o['account_id'])}, {o.get('carrier')}) {overdue} min overdue",
                    f"Status BOOKED with no pickup time, {overdue} min after the pickup window ended at "
                    f"{end:%H:%M} (rule: >= {MISSED_PICKUP_GRACE_MINUTES} min); {fault}.",
                    "rule: BOOKED past pickup window end", [o["order_id"]], [o["account_id"]],
                    "Chase the carrier and check failed-pickup credit eligibility",
                ))
        if status in ("PICKED_UP", "DELIVERED") and o.get("cancellation_requested_at"):
            alerts.append(_alert(
                "unusual_order", "info",
                f"Cancellation requested after pickup: {o['order_id']} ({names.get(o['account_id'])})",
                f"Cancellation requested {o['cancellation_requested_at']:%Y-%m-%d %H:%M} but the order is {status}; "
                "it cannot be cancelled and needs the return-to-origin workflow.",
                "rule: cancellation request on picked-up order", [o["order_id"]], [o["account_id"]],
                "Offer return-to-origin to the customer",
            ))
    for carrier, orders in missed_by_carrier.items():
        accounts = {o["account_id"] for o in orders}
        if len(accounts) >= 2:
            alerts.append(_alert(
                "multi_customer", "critical", f"{carrier}: missed pickups at {len(accounts)} accounts",
                f"{len(orders)} missed pickups with {carrier} across {len(accounts)} accounts.",
                "rule: missed pickups grouped by carrier", [o["order_id"] for o in orders], list(accounts),
                f"Raise the issue with {carrier} and notify affected accounts",
            ))
    return alerts


_ORDER = {"critical": 0, "warning": 1, "info": 2}


def all_alerts(principal: Principal) -> list[dict]:
    alerts = sla_alerts(principal) + spike_alerts() + cluster_alerts() + order_alerts()
    return sorted(alerts, key=lambda a: _ORDER[a["severity"]])
