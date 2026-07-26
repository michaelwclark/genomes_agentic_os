#!/usr/bin/env python3
"""Build production-safe LOS Tenant Runtime Operations."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import urllib.request
from pathlib import Path


HEALTH_URL_DEFAULT = "https://navyfederal.los.lenderscooperative.com/api/health_check"

PREAMBLE = """PYTHONWARNINGS=ignore DD_TRACE_ENABLED=false DD_TRACE_STARTUP_LOGS=false python manage.py shell -i python

exec(\"\"\"
import logging

for name in [
    "botocore",
    "boto3",
    "s3transfer",
    "urllib3",
    "ddtrace",
    "ddtrace.internal",
]:
    logging.getLogger(name).setLevel(logging.WARNING)

logging.getLogger().setLevel(logging.WARNING)
print("quieted noisy loggers")
\"\"\")
"""


def load_aliases() -> dict[str, list[str]]:
    alias_path = Path(__file__).resolve().parents[1] / "references" / "tenant-aliases.json"
    with alias_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_health(url: str | None) -> dict:
    if not url:
        return {}
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network/environment dependent
        return {"health_fetch_error": f"{type(exc).__name__}: {exc}", "health_url": url}


def emit_script(body: str) -> str:
    return PREAMBLE + "\nexec(\"\"\"\n" + body.rstrip() + "\n\"\"\")\n"


def dump_python(value) -> str:
    return repr(value)


def shared_tenant_helpers(aliases: dict[str, list[str]], health: dict) -> str:
    return f"""
import json
import re
from django.conf import settings
from django_tenants.utils import get_public_schema_name, schema_context

PROD_HEALTH = {dump_python(health)}
TENANT_ALIASES = {dump_python(aliases)}


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def print_json(label, value):
    print(label)
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def thin_health():
    return {{
        "env": PROD_HEALTH.get("Environment"),
        "build": PROD_HEALTH.get("Build Number"),
        "branch": PROD_HEALTH.get("Branch Name"),
        "commit": PROD_HEALTH.get("Commit ID"),
        "status": PROD_HEALTH.get("Status"),
    }}


def alias_candidates(query):
    needles = [query]
    query_norm = norm(query)
    for alias_key, values in TENANT_ALIASES.items():
        all_values = [alias_key] + values
        if query_norm in {{norm(item) for item in all_values}}:
            needles.extend(all_values)
    deduped = []
    seen = set()
    for item in needles:
        item_norm = norm(item)
        if item_norm and item_norm not in seen:
            seen.add(item_norm)
            deduped.append(item)
    return deduped


def load_tenant_rows():
    from los.organizations.models import Organization

    with schema_context(get_public_schema_name()):
        field_names = {{field.name for field in Organization._meta.get_fields()}}
        qs = Organization.objects.using("default").all()
        if "tenant_type" in field_names:
            qs = qs.filter(tenant_type=getattr(settings, "ORG_TENANT_NAME", "organization"))
        if "is_ready" in field_names:
            qs = qs.filter(is_ready=True)
        if "is_deleted" in field_names:
            qs = qs.filter(is_deleted=False)
        qs = qs.order_by("name", "schema_name")

        rows = []
        for org in qs:
            try:
                domains = list(org.domains.using("default").values_list("domain", flat=True))
            except Exception as exc:
                domains = [f"domain lookup failed: {{type(exc).__name__}}: {{exc}}"]
            rows.append({{
                "id": getattr(org, "id", None),
                "name": getattr(org, "name", None),
                "schema_name": getattr(org, "schema_name", None),
                "tenant_type": getattr(org, "tenant_type", None),
                "code": getattr(org, "code", None),
                "bank_code": getattr(org, "bank_code", None),
                "fi_bank_code": getattr(org, "fi_bank_code", None),
                "in_production": getattr(org, "in_production", None),
                "is_ready": getattr(org, "is_ready", None),
                "domains": domains,
            }})
        return rows


def thin_tenant(row):
    return {{
        "name": row.get("name"),
        "schema_name": row.get("schema_name"),
        "domains": (row.get("domains") or [])[:2],
        "in_production": row.get("in_production"),
        "is_ready": row.get("is_ready"),
        "match_score": row.get("match_score"),
    }}


def tenant_haystack(row):
    values = [
        row.get("name"),
        row.get("schema_name"),
        row.get("code"),
        row.get("bank_code"),
        row.get("fi_bank_code"),
    ]
    values.extend(row.get("domains") or [])
    return [str(value) for value in values if value not in (None, "")]


def score_tenant(row, needles):
    best = 0
    haystack = tenant_haystack(row)
    for needle in needles:
        n = norm(needle)
        if not n:
            continue
        for value in haystack:
            h = norm(value)
            if not h:
                continue
            if n == h:
                best = max(best, 100)
            elif n in h:
                best = max(best, 80)
            elif h in n:
                best = max(best, 65)
    return best


def score_tenant_rows(query, rows=None):
    rows = rows if rows is not None else load_tenant_rows()
    needles = alias_candidates(query)
    scored = []
    for row in rows:
        score = score_tenant(row, needles)
        if score:
            row_copy = dict(row)
            row_copy["match_score"] = score
            scored.append(row_copy)
    scored.sort(key=lambda item: (-item["match_score"], item.get("name") or ""))
    return scored


def resolve_tenant(query):
    rows = load_tenant_rows()
    scored = score_tenant_rows(query, rows)

    if not scored or scored[0]["match_score"] < 65:
        print_json("No confident tenant match. Top candidates:", [thin_tenant(row) for row in scored[:8]])
        print(f"available_tenant_count={{len(rows)}}")
        raise SystemExit(2)

    top_score = scored[0]["match_score"]
    top = [row for row in scored if row["match_score"] == top_score]
    if len(top) > 1:
        print_json("Ambiguous tenant match. Refine the tenant name or schema.", [thin_tenant(row) for row in top[:5]])
        raise SystemExit(2)

    print_json("Resolved tenant:", thin_tenant(scored[0]))
    return scored[0]
"""


def tenant_map_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    return textwrap.dedent(
        shared_tenant_helpers(aliases, health)
        + f"""
FULL_TENANT_MAP = {bool(args.full)}
TENANT_QUERIES = {dump_python(args.query or [])}
TENANT_LIMIT = {int(args.limit)}

print_json("prod_health", thin_health())
rows = load_tenant_rows()
print(f"tenant_count={{len(rows)}}")

queries = TENANT_QUERIES or list(TENANT_ALIASES.keys())
for query in queries:
    matches = score_tenant_rows(query, rows)[:3]
    print_json(f"tenant_match query={{query}}", [thin_tenant(row) for row in matches])

if FULL_TENANT_MAP:
    selected = [thin_tenant(row) for row in rows[:TENANT_LIMIT]]
    print_json("tenant_map_compact", selected)
    if len(rows) > TENANT_LIMIT:
        print(f"tenant_map_truncated={{len(rows) - TENANT_LIMIT}}")
else:
    print("tenant_map_full_omitted=true")
    print("rerun_generator_with=tenant-map --full --limit N only when you need a compact full list")
"""
    ).strip()


def servicing_funds_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    return textwrap.dedent(
        shared_tenant_helpers(aliases, health)
        + f"""
from datetime import date, timedelta
from decimal import Decimal
import logging

from django.db.models import Q

TENANT_QUERY = {dump_python(args.tenant)}
LOAN_NUMBER = {dump_python(args.loan_number)}
APPLICATION_NUMBER = {dump_python(args.application_number)}
BUSINESS_NAME = {dump_python(args.business_name)}
EXPECTED_UI_FUNDS_AVAILABLE = {dump_python(args.expected_ui_funds_available)}
EXPECTED_UI_PRINCIPAL_BALANCE = {dump_python(args.expected_ui_principal_balance)}
AROUND_DATE = {dump_python(args.around_date)}
WINDOW_DAYS = {int(args.window_days)}
INCLUDE_VENTURES_LIVE = {bool(args.include_ventures_live)}
MAX_PAYMENT_ROWS = {int(args.max_payment_rows)}
VERBOSE = {bool(args.verbose)}

for logger_name in ["redis", "redis.connection", "django_redis", "django_redis.cache"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)


def dec(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def money(value):
    value = dec(value)
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01")))


def public_dict(obj, fields):
    return {{field: getattr(obj, field, None) for field in fields}}


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)
schema_name = tenant["schema_name"]

with schema_context(schema_name):
    from django.db import models
    from django.db.models.functions import Cast
    from los.servicing.models import LoanValidation, PaymentHistory

    query = Q()
    if LOAN_NUMBER:
        query |= Q(loan_number=str(LOAN_NUMBER))
    if APPLICATION_NUMBER:
        query |= Q(application_number=APPLICATION_NUMBER)
    if BUSINESS_NAME:
        query |= Q(business_name__icontains=BUSINESS_NAME)
    if not query:
        raise SystemExit("Provide loan_number, application_number, or business_name.")

    loans = list(LoanValidation.objects.filter(query).order_by("-modified")[:10])
    print(f"loan_matches={{len(loans)}}")
    for candidate in loans:
        print_json("Loan candidate:", public_dict(candidate, [
            "id",
            "loan_number",
            "application_number",
            "business_name",
            "loan_status",
            "loan_sub_status",
            "current_approval_amount",
            "initial_approved_amount",
            "outstanding_balance",
            "funds_available",
            "total_amount_due",
            "payment_account_id",
            "modified",
        ]))

    if not loans:
        raise SystemExit(1)

    loan = loans[0]
    approved_basis = dec(loan.current_approval_amount) or dec(loan.initial_approved_amount)
    outstanding_balance = dec(loan.outstanding_balance)
    funds_available = dec(loan.funds_available)
    total_undisbursed = dec(loan.total_undisbursed_amount)

    calculations = {{
        "approved_basis": money(approved_basis),
        "outstanding_balance": money(outstanding_balance),
        "stored_funds_available": money(funds_available),
        "total_undisbursed_amount": money(total_undisbursed),
        "expected_from_balance": None,
        "delta_stored_minus_expected": None,
        "implied_balance_from_stored_funds": None,
        "expected_ui_funds_available": EXPECTED_UI_FUNDS_AVAILABLE,
        "expected_ui_principal_balance": EXPECTED_UI_PRINCIPAL_BALANCE,
    }}
    if approved_basis is not None and outstanding_balance is not None:
        expected_from_balance = approved_basis - outstanding_balance
        calculations["expected_from_balance"] = money(expected_from_balance)
        if funds_available is not None:
            calculations["delta_stored_minus_expected"] = money(funds_available - expected_from_balance)
    if approved_basis is not None and funds_available is not None:
        calculations["implied_balance_from_stored_funds"] = money(approved_basis - funds_available)
    print_json("Funds available arithmetic:", calculations)

    if AROUND_DATE:
        center = date.fromisoformat(AROUND_DATE)
        start = center - timedelta(days=WINDOW_DAYS)
        end = center + timedelta(days=WINDOW_DAYS)
    else:
        start = None
        end = None

    history_all = PaymentHistory.objects.filter(Q(loan=loan) | Q(loan_number=loan.loan_number))
    if start and end:
        history_all = history_all.filter(entry_date__range=(start, end))
    history = (
        history_all.filter(trans_code__regex=r"^\\d+$")
        .annotate(numeric_trans_code=Cast("trans_code", output_field=models.IntegerField()))
        .filter(numeric_trans_code__range=(300, 397))
        .order_by("-entry_date", "-created")[:MAX_PAYMENT_ROWS]
    )

    principal_sum = Decimal("0")
    rows = []
    for item in history:
        principal_sum += dec(item.principal_amount) or Decimal("0")
        details = item.details if isinstance(item.details, dict) else {{}}
        row = {{
            "id": str(item.id),
            "entry_date": item.entry_date,
            "process_date": item.process_date,
            "payment_type": item.payment_type,
            "amount": money(item.amount),
            "principal_amount": money(item.principal_amount),
            "interest_amount": money(item.interest_amount),
            "trans_code": item.trans_code,
        }}
        balance_candidates = {{
            key: details.get(key)
            for key in [
                "balance",
                "Balance",
                "endingBalance",
                "endingPrincipalBalance",
                "principalBalance",
                "currentBalance",
                "totalAmountDue",
                "paymentDueDate",
            ]
            if key in details
        }}
        if balance_candidates:
            row["details_balance_candidates"] = balance_candidates
        if VERBOSE:
            row["payment_receive_date"] = item.payment_receive_date
            row["trans_sequence_number"] = item.trans_sequence_number
            row["trans_serial_number"] = item.trans_serial_number
            row["details_keys"] = sorted(details.keys())[:30]
        rows.append(row)

    print_json("Local PaymentHistory rows:", rows)
    print_json("Local PaymentHistory summary:", {{
        "unfiltered_row_count_in_window": history_all.count(),
        "ui_filtered_trans_code_range": "300-397",
        "row_count": len(rows),
        "max_payment_rows": MAX_PAYMENT_ROWS,
        "principal_sum_in_window": money(principal_sum),
        "window_start": start,
        "window_end": end,
    }})

    servicing_provider = None
    try:
        servicing_provider = loan.servicing_config.get("servicing_provider")
    except Exception as exc:
        servicing_provider = f"servicing_config lookup failed: {{type(exc).__name__}}: {{exc}}"
    print_json("Servicing provider:", servicing_provider)

    if INCLUDE_VENTURES_LIVE:
        if servicing_provider != "ventures":
            print("Skipping Ventures live read: servicing_provider is not ventures.")
        elif not loan.payment_account_id:
            print("Skipping Ventures live read: loan.payment_account_id is empty.")
        else:
            from los.services.vendors.ventures.client import VenturesClient

            kwargs = {{"records_per_page": 50, "page": 1}}
            if start:
                kwargs["effective_start_date"] = start.isoformat()
            if end:
                kwargs["effective_end_date"] = end.isoformat()
            ventures_rows = VenturesClient(loan_validation=loan).get_payment_transactions(**kwargs)
            compact_ventures_rows = []
            for item in (ventures_rows or [])[:MAX_PAYMENT_ROWS]:
                compact_ventures_rows.append({{
                    "id": item.get("id"),
                    "effectiveDate": item.get("effectiveDate"),
                    "addedDate": item.get("addedDate"),
                    "transactionType": item.get("transactionType"),
                    "amount": item.get("amount"),
                    "principal": item.get("principal"),
                    "interest": item.get("interest"),
                    "endingPrincipalBalance": item.get("endingPrincipalBalance"),
                    "totalAmountDue": item.get("totalAmountDue"),
                    "paymentDueDate": item.get("paymentDueDate"),
                }})
            print_json("Ventures live summary:", {{
                "row_count": len(ventures_rows or []),
                "printed_rows": len(compact_ventures_rows),
                "max_payment_rows": MAX_PAYMENT_ROWS,
            }})
            print_json("Ventures live compact rows:", compact_ventures_rows)
    else:
        print("Skipped Ventures live read. Re-run with --include-ventures-live if a vendor read is needed.")
"""
    ).strip()


def decline_process_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    cases = [
        {"application_number": int(item.split(":", 1)[0]), "label": item.split(":", 1)[1] if ":" in item else ""}
        for item in args.application
    ]
    template = """
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

TENANT_QUERY = __TENANT_QUERY__
APPLICATION_CASES = __APPLICATION_CASES__
MAX_TASK_ROWS = __MAX_TASK_ROWS__
MAX_AGGREGATOR_ROWS = __MAX_AGGREGATOR_ROWS__
MAX_AUDIT_ROWS = __MAX_AUDIT_ROWS__
COMPACT_OUTPUT = __COMPACT_OUTPUT__


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def actor_name(user):
    if not user:
        return None
    return getattr(user, "name", None) or getattr(user, "username", None) or str(user)


def status_row(status):
    if not status:
        return None
    return {
        "id": getattr(status, "id", None),
        "code": getattr(status, "code", None),
        "phase": getattr(status, "phase", None),
        "status": getattr(status, "status", None),
        "borrower_status": getattr(status, "borrower_status", None),
        "terminal_status": getattr(status, "terminal_status", None),
    }


def task_name(task):
    if not task:
        return None
    if task.task_map_id and task.task_map:
        return task.task_map.name
    return task.task_type


def task_status(task):
    if not task:
        return None
    try:
        return task.get_status_display()
    except Exception:
        return getattr(task, "status", None)


def task_row(task):
    if not task:
        return None
    task_map = task.task_map if task.task_map_id else None
    creator = task.creator_task
    return {
        "id": task.id,
        "slug": str(task.slug),
        "task_type": task.task_type,
        "task_name": task_name(task),
        "sub_task": getattr(task_map, "sub_task", None),
        "sub_task_type": getattr(task_map, "sub_task_type", None),
        "level": task.level,
        "status": task_status(task),
        "status_id": task.status,
        "status_reason": task.status_reason,
        "internal_remarks": task.internal_remarks,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "is_active": task.is_active,
        "is_manual": task.is_manual,
        "actor": actor_name(task.actor),
        "created": task.created,
        "modified": task.modified,
        "action_taken_at": task.action_taken_at,
        "completion_date": task.completion_date,
        "creator_task": {
            "id": getattr(creator, "id", None),
            "task_name": task_name(creator),
            "status": task_status(creator),
        } if creator else None,
    }


def thin_task_row(task):
    row = task_row(task)
    if not row:
        return None
    return {
        "id": row["id"],
        "task_name": row["task_name"],
        "sub_task": row["sub_task"],
        "sub_task_type": row["sub_task_type"],
        "status": row["status"],
        "status_reason": row["status_reason"],
        "internal_remarks": row["internal_remarks"],
        "actor": row["actor"],
        "modified": row["modified"],
    }


def compact_decline_initiated_from(details):
    data = (details or {}).get("decline_initiated_from_data") or {}
    return {
        "present": bool(data),
        "origination_task_id": data.get("origination_task_id"),
        "origination_task_name": data.get("origination_task_name"),
        "loan_request_status_code": data.get("loan_request_status_code"),
        "loan_current_task_id": data.get("loan_current_task_id"),
        "integration_rule_name_changed": data.get("integration_rule_name_changed"),
        "keys": sorted(data.keys()),
    }


def compact_subtask_detail(item):
    task_map = item.get("task_map") if isinstance(item, dict) else {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "task_name": (task_map or {}).get("name"),
        "sub_task": (task_map or {}).get("sub_task"),
        "sub_task_type": (task_map or {}).get("sub_task_type"),
        "level": item.get("level"),
        "is_workflow_end": item.get("is_workflow_end"),
        "next_task_name": item.get("next_task_name"),
        "action_taken_at": item.get("action_taken_at"),
    }


def aggregator_row(aggregator):
    details = aggregator.sub_task_details or []
    return {
        "id": aggregator.id,
        "task_name": aggregator.task_name,
        "task_id": aggregator.task_id,
        "status": aggregator.status,
        "stage": aggregator.stage,
        "display_order": aggregator.display_order,
        "is_valid": aggregator.is_valid,
        "history_count": len(details),
        "history_tail": [compact_subtask_detail(item) for item in details[-2:]],
    }


def compact_event(entry):
    events = []
    try:
        events = [getattr(event, "id", None) or getattr(event, "description", None) for event in entry.get_events()]
    except Exception:
        pass
    changes = getattr(entry, "changes", None)
    change_keys = sorted(changes.keys()) if isinstance(changes, dict) else []
    additional_data = getattr(entry, "additional_data", None)
    additional_keys = sorted(additional_data.keys()) if isinstance(additional_data, dict) else []
    return {
        "timestamp": getattr(entry, "timestamp", None),
        "actor": actor_name(getattr(entry, "actor", None)),
        "object_pk": getattr(entry, "object_pk", None),
        "object_repr": getattr(entry, "object_repr", None),
        "changes_keys": change_keys[:12],
        "additional_data_keys": additional_keys[:12],
        "events": events[:4],
        "summary": str(entry)[:220],
    }


def get_content_type(model):
    try:
        return ContentType.objects.get_for_model(model)
    except Exception:
        return None


def print_recent_events(label, model, object_ids):
    from los.auditlog.models import EventLog, LogEntry

    ct = get_content_type(model)
    if not ct or not object_ids:
        print_json(label, {"row_count": 0, "rows": []})
        return
    object_pks = [str(item) for item in object_ids if item]
    rows = []
    for klass in [EventLog, LogEntry]:
        try:
            rows.extend(
                list(
                    klass.objects.filter(content_type=ct, object_pk__in=object_pks)
                    .select_related("actor")
                    .order_by("-timestamp")[:MAX_AUDIT_ROWS]
                )
            )
        except Exception as exc:
            rows.append({"error": f"{klass.__name__}: {type(exc).__name__}: {exc}"})
    compact = [compact_event(row) if not isinstance(row, dict) else row for row in rows[:MAX_AUDIT_ROWS]]
    print_json(label, {"row_count": len(compact), "max_rows": MAX_AUDIT_ROWS, "rows": compact})


def open_service_request_rows(loan):
    try:
        rows = []
        for sr in loan.servicerequest_set.filter(request_status__terminal_status=False).order_by("-created")[:5]:
            workflow = getattr(sr, "task_workflow", None)
            rows.append({
                "id": sr.id,
                "reference_id": getattr(sr, "reference_id", None),
                "task_workflow": getattr(workflow, "name", None),
                "task_workflow_sub_type": getattr(workflow, "sub_type", None),
                "request_status": status_row(getattr(sr, "request_status", None)),
                "created": getattr(sr, "created", None),
                "modified": getattr(sr, "modified", None),
            })
        return rows
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]


def summarize_case(case):
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.models import DenialReason, Loan, LoanDecision, LoanTaskAggregator

    app_number = case["application_number"]
    expected_label = case.get("label") or str(app_number)
    loan = Loan.objects.select_related("request_status", "current_task", "current_task__task_map").filter(
        application_number=app_number
    ).first()
    if not loan:
        if COMPACT_OUTPUT:
            print_compact(f"case {expected_label} loan_not_found", {"application_number": app_number})
        else:
            print_json(f"case {expected_label} loan not found", {"application_number": app_number})
        return None

    decline_data = compact_decline_initiated_from(loan.details)
    current_task = loan.current_task
    origin_task = None
    if decline_data["origination_task_id"]:
        origin_task = (
            TaskExecution.objects.select_related("task_map", "actor", "creator_task", "creator_task__task_map")
            .filter(id=decline_data["origination_task_id"])
            .first()
        )

    terminal_status_ids = TaskExecution.terminal_statuses()
    decline_tasks = list(
        TaskExecution.objects.select_related("task_map", "actor", "creator_task", "creator_task__task_map")
        .filter(entity=loan, task_map__name=TaskMap.TASK_LOAN_DECLINE)
        .order_by("-created")[:MAX_TASK_ROWS]
    )
    final_review_terminal = TaskExecution.objects.filter(
        entity=loan,
        task_map__name=TaskMap.TASK_LOAN_DECLINE,
        task_map__sub_task=getattr(TaskMap, "SUB_TASK_REVIEW", "review"),
        task_map__sub_task_type=getattr(TaskMap, "SUB_TASK_TYPE_DECLINE_NOTICE", "decline_notice"),
        status__in=terminal_status_ids,
    ).exists()

    aggregator_qs = LoanTaskAggregator.objects.filter(loan=loan)
    terminal_aggregator_count = aggregator_qs.filter(
        task_name=TaskExecution.TERMINAL_TASK,
        is_valid=True,
    ).count()
    decline_aggregator_count = aggregator_qs.filter(
        task_name=TaskMap.TASK_LOAN_DECLINE,
        is_valid=True,
    ).count()
    aggregators = list(
        aggregator_qs
        .filter(Q(is_valid=True) | Q(task_name__in=[TaskMap.TASK_LOAN_DECLINE, TaskExecution.TERMINAL_TASK]))
        .order_by("display_order", "id")[:MAX_AGGREGATOR_ROWS]
    )
    open_service_requests = open_service_request_rows(loan)
    try:
        open_service_request_count = loan.servicerequest_set.filter(request_status__terminal_status=False).count()
    except Exception:
        open_service_request_count = len(open_service_requests)
    denial_reason_count = DenialReason.objects.filter(loan=loan).count()
    decline_loan_decision_count = LoanDecision.objects.filter(loan=loan, decision=LoanDecision.DECLINE).count()
    conclusion = {
        "application_number": loan.application_number,
        "ui_would_show_completed_banner_when_terminal_task_present": bool(terminal_aggregator_count),
        "ui_would_show_decline_banner_when_no_terminal_and_decline_key_present": bool(
            not terminal_aggregator_count and decline_data["present"]
        ),
        "loan_request_status_terminal": bool(getattr(loan.request_status, "terminal_status", False)),
        "decline_key_present": decline_data["present"],
        "final_review_decline_notice_terminal": final_review_terminal,
        "decline_aggregator_count": decline_aggregator_count,
        "terminal_aggregator_count": terminal_aggregator_count,
        "open_service_request_count": open_service_request_count,
        "probable_stuck_shape": bool(decline_data["present"] and final_review_terminal and not terminal_aggregator_count),
        "mutation_included": False,
    }
    if COMPACT_OUTPUT:
        print_compact(f"case {expected_label}", {
            "label": expected_label,
            "application_number": loan.application_number,
            "loan_id": loan.id,
            "borrower_name": getattr(loan, "business_name", None) or getattr(loan, "name", None) or str(loan),
            "request_status": status_row(loan.request_status),
            "is_decline_in_progress": bool(getattr(loan, "is_decline_in_progress", False)),
            "decline_started_from": {
                "present": decline_data["present"],
                "origination_task_id": decline_data["origination_task_id"],
                "origination_task_name": decline_data["origination_task_name"],
                "loan_request_status_code": decline_data["loan_request_status_code"],
                "loan_current_task_id": decline_data["loan_current_task_id"],
            },
            "current_task": thin_task_row(current_task),
            "originating_task": thin_task_row(origin_task),
            "final_review_decline_notice_terminal": final_review_terminal,
            "decline_aggregator_count": decline_aggregator_count,
            "terminal_aggregator_count": terminal_aggregator_count,
            "denial_reason_count": denial_reason_count,
            "decline_loan_decision_count": decline_loan_decision_count,
            "open_service_request_count": open_service_request_count,
            "ui_completed_banner": conclusion["ui_would_show_completed_banner_when_terminal_task_present"],
            "ui_decline_banner": conclusion["ui_would_show_decline_banner_when_no_terminal_and_decline_key_present"],
            "probable_stuck_shape": conclusion["probable_stuck_shape"],
        })
        return conclusion

    loan_summary = {
        "label": expected_label,
        "id": loan.id,
        "application_number": loan.application_number,
        "loan_number": loan.loan_number,
        "borrower_name": getattr(loan, "business_name", None) or getattr(loan, "name", None) or str(loan),
        "request_status": status_row(loan.request_status),
        "request_status_terminal": bool(getattr(loan.request_status, "terminal_status", False)),
        "is_decline_in_progress": bool(getattr(loan, "is_decline_in_progress", False)),
        "decline_initiated_from_data": decline_data,
        "current_task": task_row(current_task),
        "originating_task": task_row(origin_task),
        "underwriter_decision": getattr(loan, "underwriter_decision", None),
        "underwriter_decision_date": getattr(loan, "underwriter_decision_date", None),
        "modified": loan.modified,
    }
    print_json(f"case {expected_label} loan summary", loan_summary)

    print_json(f"case {expected_label} decline tasks", {
        "row_count_printed": len(decline_tasks),
        "max_rows": MAX_TASK_ROWS,
        "rows": [task_row(task) for task in decline_tasks],
    })
    print_json(f"case {expected_label} task aggregators", {
        "row_count_printed": len(aggregators),
        "max_rows": MAX_AGGREGATOR_ROWS,
        "rows": [aggregator_row(agg) for agg in aggregators],
    })
    print_json(f"case {expected_label} related records", {
        "denial_reason_count": denial_reason_count,
        "decline_loan_decision_count": decline_loan_decision_count,
        "open_service_requests": open_service_requests,
    })

    audit_task_ids = [task.id for task in decline_tasks]
    if origin_task:
        audit_task_ids.append(origin_task.id)
    if current_task:
        audit_task_ids.append(current_task.id)
    print_recent_events(f"case {expected_label} loan audit/event rows", Loan, [loan.id])
    print_recent_events(f"case {expected_label} task audit/event rows", TaskExecution, sorted(set(audit_task_ids)))

    print_json(f"case {expected_label} conclusion", conclusion)
    return conclusion


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)
schema_name = tenant["schema_name"]

with schema_context(schema_name):
    conclusions = []
    for case in APPLICATION_CASES:
        result = summarize_case(case)
        if result:
            conclusions.append(result)
    overall = {
        "tenant_schema": schema_name,
        "case_count": len(conclusions),
        "stuck_candidates": [
            item["application_number"]
            for item in conclusions
            if item["probable_stuck_shape"]
        ],
        "completed_like_candidates": [
            item["application_number"]
            for item in conclusions
            if item["ui_would_show_completed_banner_when_terminal_task_present"]
        ],
        "read_only": True,
        "next_step": "If a stuck candidate is confirmed, request a separate approval-gated mutation script with exact target IDs and before/after checks.",
    }
    if COMPACT_OUTPUT:
        print_compact("overall comparison", overall)
    else:
        print_json("overall comparison", overall)
"""
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_CASES__", dump_python(cases))
        .replace("__MAX_TASK_ROWS__", str(int(args.max_task_rows)))
        .replace("__MAX_AGGREGATOR_ROWS__", str(int(args.max_aggregator_rows)))
        .replace("__MAX_AUDIT_ROWS__", str(int(args.max_audit_rows)))
        .replace("__COMPACT_OUTPUT__", str(not bool(args.include_details)))
    )
    return textwrap.dedent(body).strip()


def decline_process_repair_plan_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    cases = [
        {"application_number": int(item.split(":", 1)[0]), "label": item.split(":", 1)[1] if ":" in item else ""}
        for item in args.application
    ]
    template = """
TENANT_QUERY = __TENANT_QUERY__
APPLICATION_CASES = __APPLICATION_CASES__


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def resolve_tenant_compact(query):
    rows = load_tenant_rows()
    scored = score_tenant_rows(query, rows)
    if not scored or scored[0]["match_score"] < 65:
        print_compact("tenant_resolution_error", {
            "query": query,
            "available_tenant_count": len(rows),
            "top_candidates": [thin_tenant(row) for row in scored[:5]],
        })
        raise SystemExit(2)

    top_score = scored[0]["match_score"]
    top = [row for row in scored if row["match_score"] == top_score]
    if len(top) > 1:
        print_compact("tenant_resolution_error", {
            "query": query,
            "reason": "ambiguous",
            "top_candidates": [thin_tenant(row) for row in top[:5]],
        })
        raise SystemExit(2)

    print_compact("resolved_tenant", thin_tenant(scored[0]))
    return scored[0]


def actor_name(user):
    if not user:
        return None
    return getattr(user, "name", None) or getattr(user, "username", None) or str(user)


def status_row(status):
    if not status:
        return None
    return {
        "code": getattr(status, "code", None),
        "phase": getattr(status, "phase", None),
        "status": getattr(status, "status", None),
        "borrower_status": getattr(status, "borrower_status", None),
        "terminal_status": getattr(status, "terminal_status", None),
    }


def task_name(task):
    if not task:
        return None
    if task.task_map_id and task.task_map:
        return task.task_map.name
    return task.task_type


def task_status(task):
    if not task:
        return None
    try:
        return task.get_status_display()
    except Exception:
        return getattr(task, "status", None)


def task_summary(task):
    if not task:
        return None
    task_map = task.task_map if task.task_map_id else None
    return {
        "id": task.id,
        "task_type": task.task_type,
        "task_name": task_name(task),
        "sub_task": getattr(task_map, "sub_task", None),
        "sub_task_type": getattr(task_map, "sub_task_type", None),
        "status": task_status(task),
        "status_reason": task.status_reason,
        "internal_remarks": task.internal_remarks,
        "actor": actor_name(task.actor),
        "modified": task.modified,
    }


def decline_started_from(details):
    data = (details or {}).get("decline_initiated_from_data") or {}
    return {
        "present": bool(data),
        "origination_task_id": data.get("origination_task_id"),
        "origination_task_name": data.get("origination_task_name"),
        "loan_request_status_code": data.get("loan_request_status_code"),
        "loan_current_task_id": data.get("loan_current_task_id"),
    }


def compact_interface(obj, soft_keys, hard_keys):
    if not obj:
        return {"exists": False}
    details = getattr(obj, "details", None) or {}
    return {
        "exists": True,
        "modified": getattr(obj, "modified", None),
        "soft_pull_present": any(bool(details.get(key)) for key in soft_keys),
        "hard_pull_present": any(bool(details.get(key)) for key in hard_keys),
        "details_keys": sorted(details.keys())[:12],
    }


def hard_pull_state(loan):
    state = {
        "uses_credit_bureau_for_prequalification": None,
        "needs_fico_hard_pull": None,
        "credit_bureau_interface": None,
        "experian_interface": None,
        "fico_interface": None,
    }
    try:
        state["uses_credit_bureau_for_prequalification"] = bool(loan.uses_credit_bureau_for_prequalification())
    except Exception as exc:
        state["uses_credit_bureau_for_prequalification"] = f"{type(exc).__name__}: {exc}"
    try:
        state["needs_fico_hard_pull"] = bool(loan.needs_fico_hard_pull())
    except Exception as exc:
        state["needs_fico_hard_pull"] = f"{type(exc).__name__}: {exc}"
    for attr, soft_keys, hard_keys in [
        ("credit_bureau_interface", ["soft_pull_cbr_data"], ["cbr_data"]),
        ("experian_interface", ["soft_pull_cbr_data"], ["cbr_data"]),
        ("fico_interface", ["soft_pull_fico_data"], ["fico_data"]),
    ]:
        try:
            state[attr] = compact_interface(getattr(loan, attr, None), soft_keys, hard_keys)
        except Exception as exc:
            state[attr] = {"error": f"{type(exc).__name__}: {exc}"}
    return state


def summarize_repair_plan(case):
    from los.backoffice.constants import InternalRemarks
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.models import DenialReason, Loan, LoanDecision, LoanTaskAggregator, RequestStatus

    app_number = case["application_number"]
    label = case.get("label") or str(app_number)
    loan = Loan.objects.select_related(
        "request_status",
        "current_task",
        "current_task__task_map",
        "current_task__actor",
    ).filter(application_number=app_number).first()
    if not loan:
        print_compact(f"repair_plan {label}", {
            "application_number": app_number,
            "found": False,
            "eligible": False,
            "reason": "loan_not_found",
            "dry_run": True,
        })
        return None

    terminal_status_ids = TaskExecution.terminal_statuses()
    decline_task = TaskExecution.objects.select_related("task_map", "actor").filter(
        entity=loan,
        task_map__name=TaskMap.TASK_LOAN_DECLINE,
        task_map__sub_task=getattr(TaskMap, "SUB_TASK_REVIEW", "review"),
        task_map__sub_task_type=getattr(TaskMap, "SUB_TASK_TYPE_DECLINE_NOTICE", "decline_notice"),
        status__in=terminal_status_ids,
    ).order_by("-modified", "-created").first()
    origin_data = decline_started_from(loan.details)
    origin_task = None
    if origin_data["origination_task_id"]:
        origin_task = TaskExecution.objects.select_related("task_map", "actor").filter(
            id=origin_data["origination_task_id"]
        ).first()

    terminal_task_count = TaskExecution.objects.filter(
        entity=loan,
        task_type=TaskExecution.TERMINAL_TASK,
        is_valid=True,
    ).count()
    terminal_aggregator_count = LoanTaskAggregator.objects.filter(
        loan=loan,
        task_name=TaskExecution.TERMINAL_TASK,
        is_valid=True,
    ).count()
    decline_aggregator_count = LoanTaskAggregator.objects.filter(
        loan=loan,
        task_name=TaskMap.TASK_LOAN_DECLINE,
        is_valid=True,
    ).count()
    open_service_request_count = loan.servicerequest_set.filter(request_status__terminal_status=False).count()
    denial_reason_count = DenialReason.objects.filter(loan=loan).count()
    decline_loan_decision_count = LoanDecision.objects.filter(loan=loan, decision=LoanDecision.DECLINE).count()
    hard_pull = hard_pull_state(loan)

    request_status = getattr(loan, "request_status", None)
    current_task = loan.current_task
    preconditions = {
        "decline_key_present": origin_data["present"],
        "request_status_is_stuck_decline_accept": bool(
            getattr(request_status, "code", None) == "LOAN_DECLINE__ACCEPTED"
            and not getattr(request_status, "terminal_status", False)
        ),
        "final_decline_notice_task_terminal": bool(decline_task),
        "current_task_is_decline_notice": bool(
            current_task
            and current_task.task_map_id
            and current_task.task_map.name == TaskMap.TASK_LOAN_DECLINE
            and current_task.task_map.sub_task == getattr(TaskMap, "SUB_TASK_REVIEW", "review")
            and current_task.task_map.sub_task_type == getattr(TaskMap, "SUB_TASK_TYPE_DECLINE_NOTICE", "decline_notice")
            and current_task.status in terminal_status_ids
        ),
        "current_task_marked_go_to_fico": bool(
            current_task and current_task.internal_remarks == InternalRemarks.GO_TO_FICO.value
        ),
        "origin_task_denied": bool(origin_task and origin_task.status == TaskExecution.DENIED),
        "no_open_service_requests": open_service_request_count == 0,
        "has_denial_reasons": denial_reason_count > 0,
        "has_decline_loan_decision": decline_loan_decision_count > 0,
        "no_terminal_task": terminal_task_count == 0,
        "no_terminal_aggregator": terminal_aggregator_count == 0,
    }
    shape_ok = all(preconditions.values())
    needs_hard_pull = hard_pull["needs_fico_hard_pull"] is True
    hard_pull_unknown = not isinstance(hard_pull["needs_fico_hard_pull"], bool)
    eligible_for_terminal_backfill = bool(shape_ok and not needs_hard_pull and not hard_pull_unknown)

    if needs_hard_pull:
        classification = "blocked_needs_hard_pull"
        proposed_operations = [
            "Do not terminalize directly while loan.needs_fico_hard_pull() is true.",
            "Resolve the intended hard-pull workflow path first, then re-run the normal next-task/terminal workflow.",
        ]
    elif hard_pull_unknown:
        classification = "blocked_hard_pull_state_unknown"
        proposed_operations = [
            "Do not terminalize until hard-pull state can be evaluated cleanly.",
        ]
    elif eligible_for_terminal_backfill:
        classification = "eligible_for_approval_gated_terminal_backfill"
        proposed_operations = [
            "Run the normal END-workflow equivalent: update decline-task aggregator, create/get terminal TaskExecution with creator_task set to the accepted LOAN_DECLINE task, run terminal creator hooks, run decline workflow_end_hook, and set moved_to_terminal_at.",
            "The expected loan request_status after the hook is APPLICATION__DECLINED.",
        ]
    else:
        classification = "not_eligible_shape_mismatch"
        proposed_operations = [
            "No write should be attempted until failed preconditions are reviewed.",
        ]

    row = {
        "application_number": loan.application_number,
        "loan_id": str(loan.id),
        "label": label,
        "request_status": status_row(request_status),
        "current_task": task_summary(current_task),
        "decline_notice_task": task_summary(decline_task),
        "originating_task": task_summary(origin_task),
        "counts": {
            "decline_aggregator_count": decline_aggregator_count,
            "terminal_task_count": terminal_task_count,
            "terminal_aggregator_count": terminal_aggregator_count,
            "open_service_request_count": open_service_request_count,
            "denial_reason_count": denial_reason_count,
            "decline_loan_decision_count": decline_loan_decision_count,
        },
        "hard_pull": hard_pull,
        "preconditions": preconditions,
        "classification": classification,
        "eligible_for_terminal_backfill": eligible_for_terminal_backfill,
        "proposed_operations": proposed_operations,
        "mutation_included": False,
        "dry_run": True,
    }
    print_compact(f"repair_plan {label}", row)
    return row


print_compact("prod_health", thin_health())
tenant = resolve_tenant_compact(TENANT_QUERY)
schema_name = tenant["schema_name"]

with schema_context(schema_name):
    rows = []
    for case in APPLICATION_CASES:
        result = summarize_repair_plan(case)
        if result:
            rows.append(result)
    print_compact("repair_plan overall", {
        "tenant_schema": schema_name,
        "case_count": len(rows),
        "eligible_for_terminal_backfill": [
            item["application_number"] for item in rows if item["eligible_for_terminal_backfill"]
        ],
        "blocked_needs_hard_pull": [
            item["application_number"] for item in rows if item["classification"] == "blocked_needs_hard_pull"
        ],
        "not_eligible": [
            item["application_number"] for item in rows
            if not item["eligible_for_terminal_backfill"] and item["classification"] != "blocked_needs_hard_pull"
        ],
        "mutation_included": False,
        "dry_run": True,
    })
"""
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_CASES__", dump_python(cases))
    )
    return textwrap.dedent(body).strip()


def decline_process_root_cause_validation_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    cases = [
        {"application_number": int(item.split(":", 1)[0]), "label": item.split(":", 1)[1] if ":" in item else ""}
        for item in args.application
    ]
    template = """
TENANT_QUERY = __TENANT_QUERY__
APPLICATION_CASES = __APPLICATION_CASES__


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def resolve_tenant_compact(query):
    rows = load_tenant_rows()
    scored = score_tenant_rows(query, rows)
    if not scored or scored[0]["match_score"] < 65:
        print_compact("tenant_resolution_error", {
            "query": query,
            "available_tenant_count": len(rows),
            "top_candidates": [thin_tenant(row) for row in scored[:5]],
        })
        raise SystemExit(2)

    top_score = scored[0]["match_score"]
    top = [row for row in scored if row["match_score"] == top_score]
    if len(top) > 1:
        print_compact("tenant_resolution_error", {
            "query": query,
            "reason": "ambiguous",
            "top_candidates": [thin_tenant(row) for row in top[:5]],
        })
        raise SystemExit(2)

    print_compact("resolved_tenant", thin_tenant(scored[0]))
    return scored[0]


def actor_name(user):
    if not user:
        return None
    return getattr(user, "name", None) or getattr(user, "username", None) or str(user)


def status_row(status):
    if not status:
        return None
    return {
        "code": getattr(status, "code", None),
        "phase": getattr(status, "phase", None),
        "status": getattr(status, "status", None),
        "borrower_status": getattr(status, "borrower_status", None),
        "terminal_status": getattr(status, "terminal_status", None),
    }


def task_name(task):
    if not task:
        return None
    if task.task_map_id and task.task_map:
        return task.task_map.name
    return task.task_type


def task_status(task):
    if not task:
        return None
    try:
        return task.get_status_display()
    except Exception:
        return getattr(task, "status", None)


def task_summary(task):
    if not task:
        return None
    task_map = task.task_map if task.task_map_id else None
    return {
        "id": task.id,
        "task_type": task.task_type,
        "task_name": task_name(task),
        "sub_task": getattr(task_map, "sub_task", None),
        "sub_task_type": getattr(task_map, "sub_task_type", None),
        "status": task_status(task),
        "status_reason": task.status_reason,
        "internal_remarks": task.internal_remarks,
        "actor": actor_name(task.actor),
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "is_active": task.is_active,
        "created": task.created,
        "modified": task.modified,
        "error": str(task.error)[:300] if task.error else None,
    }


def decline_started_from(details):
    data = (details or {}).get("decline_initiated_from_data") or {}
    return {
        "present": bool(data),
        "origination_task_id": data.get("origination_task_id"),
        "origination_task_name": data.get("origination_task_name"),
        "loan_request_status_code": data.get("loan_request_status_code"),
        "loan_current_task_id": data.get("loan_current_task_id"),
    }


def hard_pull_state(loan):
    state = {"uses_credit_bureau_for_prequalification": None, "needs_fico_hard_pull": None}
    try:
        state["uses_credit_bureau_for_prequalification"] = bool(loan.uses_credit_bureau_for_prequalification())
    except Exception as exc:
        state["uses_credit_bureau_for_prequalification"] = f"{type(exc).__name__}: {exc}"
    try:
        state["needs_fico_hard_pull"] = bool(loan.needs_fico_hard_pull())
    except Exception as exc:
        state["needs_fico_hard_pull"] = f"{type(exc).__name__}: {exc}"
    try:
        cbr_interface = getattr(loan, "credit_bureau_interface", None)
        details = getattr(cbr_interface, "details", None) or {}
        state["credit_bureau_interface"] = {
            "exists": bool(cbr_interface),
            "soft_pull_present": bool(details.get("soft_pull_cbr_data")),
            "hard_pull_present": bool(details.get("cbr_data")),
            "details_keys": sorted(details.keys())[:12],
        }
    except Exception as exc:
        state["credit_bureau_interface"] = {"error": f"{type(exc).__name__}: {exc}"}
    return state


def rule_response_summary(rule_response):
    if not rule_response:
        return None
    return {
        "task": rule_response.task,
        "sub_task": rule_response.sub_task,
        "sub_task_type": rule_response.sub_task_type,
        "task_type": rule_response.task_type,
        "level": rule_response.level,
        "rule_version": rule_response.rule_version,
        "is_final_level": rule_response.is_final_level,
        "allowed_operation_count": len(rule_response.allowed_operations or []),
        "precondition_count": len(rule_response.preconditions or []),
        "optional_precondition_count": len(rule_response.optional_preconditions or []),
    }


def build_executor_for_validation(loan, decline_task):
    from los.backoffice.tasks import task_create_bo_tasks

    executor_class = loan.get_task_executor()
    executor = executor_class(
        celery_task=task_create_bo_tasks,
        task_execution_instance=decline_task,
        task_execution_instance_id=decline_task.id,
        retries=0,
        calling_func="accept",
        entity=loan,
    )
    executor.params.creator_task = decline_task.task_map.name
    executor.params.task_type = decline_task.task_type
    executor.params.creator_sub_task = decline_task.task_map.sub_task
    executor.params.creator_sub_task_type = decline_task.task_map.sub_task_type
    executor.params.level = decline_task.level
    executor.params.last_action_status = decline_task.get_status_display()
    executor.params.remarks = decline_task.internal_remarks
    executor.params.stay_assigned = decline_task.stay_assigned
    executor.params.task_version = decline_task.task_map.task_version
    return executor


def validate_next_step(case):
    from los.backoffice.constants import InternalRemarks
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.models import Loan, LoanTaskAggregator

    app_number = case["application_number"]
    label = case.get("label") or str(app_number)
    loan = Loan.objects.select_related(
        "request_status",
        "current_task",
        "current_task__task_map",
        "current_task__actor",
    ).filter(application_number=app_number).first()
    if not loan:
        row = {"application_number": app_number, "found": False, "validation_status": "loan_not_found"}
        print_compact(f"root_cause_validation {label}", row)
        return row

    terminal_status_ids = TaskExecution.terminal_statuses()
    decline_task = TaskExecution.objects.select_related("task_map", "actor").filter(
        entity=loan,
        task_map__name=TaskMap.TASK_LOAN_DECLINE,
        task_map__sub_task=getattr(TaskMap, "SUB_TASK_REVIEW", "review"),
        task_map__sub_task_type=getattr(TaskMap, "SUB_TASK_TYPE_DECLINE_NOTICE", "decline_notice"),
        status__in=terminal_status_ids,
        internal_remarks=InternalRemarks.GO_TO_FICO.value,
    ).order_by("-modified", "-created").first()
    if not decline_task:
        row = {
            "application_number": loan.application_number,
            "loan_id": str(loan.id),
            "found": True,
            "validation_status": "accepted_go_to_fico_decline_task_not_found",
            "current_task": task_summary(loan.current_task),
            "request_status": status_row(loan.request_status),
        }
        print_compact(f"root_cause_validation {label}", row)
        return row

    cbr_tasks = list(
        TaskExecution.objects.select_related("task_map", "actor", "creator_task", "creator_task__task_map")
        .filter(entity=loan, task_map__name=TaskMap.TASK_CREDIT_BUREAU)
        .order_by("-created")[:6]
    )
    terminal_task_count = TaskExecution.objects.filter(
        entity=loan,
        task_type=TaskExecution.TERMINAL_TASK,
        is_valid=True,
    ).count()
    terminal_aggregator_count = LoanTaskAggregator.objects.filter(
        loan=loan,
        task_name=TaskExecution.TERMINAL_TASK,
        is_valid=True,
    ).count()

    executor = None
    rule_error = None
    rule_summary = None
    guard_would_skip = None
    guard_result_code = None
    validation_status = "unknown"
    try:
        executor = build_executor_for_validation(loan, decline_task)
        valid_params = executor.validate_execution_params()
        if not valid_params:
            validation_status = "executor_params_invalid"
        else:
            executor.task_hooks.pre_rules_engine_api_call_hook()
            executor.set_task_product()
            executor.get_rules_engine_response()
            rule_summary = rule_response_summary(executor.rule_response)
            guard_would_skip = bool(
                executor._loan_is_decline_in_progress()
                and executor.rule_response.task != TaskMap.TASK_LOAN_DECLINE
            )
            guard_result_code = "BO1113" if guard_would_skip else None
            if guard_would_skip and executor.rule_response.task == TaskMap.TASK_CREDIT_BUREAU:
                validation_status = "confirmed_guard_blocks_credit_bureau_handoff"
            elif guard_would_skip:
                validation_status = "confirmed_guard_blocks_non_decline_task"
            elif executor.rule_response.task == "END":
                validation_status = "rules_return_end_guard_not_root_cause"
            else:
                validation_status = "guard_does_not_explain_current_state"
    except Exception as exc:
        rule_error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        validation_status = "rules_response_or_executor_error"

    row = {
        "application_number": loan.application_number,
        "loan_id": str(loan.id),
        "label": label,
        "validation_status": validation_status,
        "request_status": status_row(loan.request_status),
        "decline_key": decline_started_from(loan.details),
        "is_decline_in_progress": bool(getattr(loan, "is_decline_in_progress", False)),
        "hard_pull": hard_pull_state(loan),
        "current_task": task_summary(loan.current_task),
        "accepted_decline_task": task_summary(decline_task),
        "next_step_rule_response": rule_summary,
        "next_step_rule_error": rule_error,
        "guard_check": {
            "loan_decline_in_progress": bool(getattr(loan, "is_decline_in_progress", False)),
            "rule_task": rule_summary.get("task") if rule_summary else None,
            "would_skip_non_loan_decline_task": guard_would_skip,
            "expected_skip_code": guard_result_code,
        },
        "existing_credit_bureau_tasks": {
            "count_printed": len(cbr_tasks),
            "rows": [task_summary(task) for task in cbr_tasks],
        },
        "terminal_counts": {
            "terminal_task_count": terminal_task_count,
            "terminal_aggregator_count": terminal_aggregator_count,
        },
        "mutation_included": False,
        "read_only": True,
    }
    print_compact(f"root_cause_validation {label}", row)
    return row


print_compact("prod_health", thin_health())
tenant = resolve_tenant_compact(TENANT_QUERY)
schema_name = tenant["schema_name"]

with schema_context(schema_name):
    rows = []
    for case in APPLICATION_CASES:
        result = validate_next_step(case)
        if result:
            rows.append(result)
    print_compact("root_cause_validation overall", {
        "tenant_schema": schema_name,
        "case_count": len(rows),
        "confirmed_guard_blocks_credit_bureau_handoff": [
            item["application_number"]
            for item in rows
            if item.get("validation_status") == "confirmed_guard_blocks_credit_bureau_handoff"
        ],
        "rules_or_executor_errors": [
            item["application_number"]
            for item in rows
            if item.get("validation_status") == "rules_response_or_executor_error"
        ],
        "guard_not_confirmed": [
            item["application_number"]
            for item in rows
            if item.get("validation_status") not in [
                "confirmed_guard_blocks_credit_bureau_handoff",
                "confirmed_guard_blocks_non_decline_task",
                "rules_response_or_executor_error",
            ]
        ],
        "mutation_included": False,
        "read_only": True,
    })
"""
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_CASES__", dump_python(cases))
    )
    return textwrap.dedent(body).strip()


def queue_depth_check_body(args: argparse.Namespace) -> str:
    health = fetch_health(args.health_url)
    template = """
import json
import os
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

PROD_HEALTH = __PROD_HEALTH__
REQUESTED_QUEUE_FILTERS = __REQUESTED_QUEUE_FILTERS__
TERMINATOR_OPEN_STATUSES = __TERMINATOR_OPEN_STATUSES__
FULL_THRESHOLD = __FULL_THRESHOLD__
MAX_QUEUES = __MAX_QUEUES__
MAX_ROWS = __MAX_ROWS__
OBSERVATIONS = []


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def safe_error(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:300]}


def thin_health():
    return {
        "env": PROD_HEALTH.get("Environment"),
        "build": PROD_HEALTH.get("Build Number"),
        "branch": PROD_HEALTH.get("Branch Name"),
        "commit": PROD_HEALTH.get("Commit ID"),
        "status": PROD_HEALTH.get("Status"),
    }


def append_unique(values, value):
    if value and value not in values:
        values.append(value)


def broker_scheme():
    broker_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    return urlparse(broker_url).scheme.split("+")[0]


def configured_queue_names():
    names = []
    append_unique(names, getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None))
    append_unique(names, getattr(settings, "AUDIT_LOG_QUEUE", None))
    append_unique(names, getattr(settings, "INTEGRATION_LOG_QUEUE", None))
    for route in (getattr(settings, "CELERY_TASK_ROUTES", {}) or {}).values():
        if isinstance(route, dict):
            append_unique(names, route.get("queue"))
    try:
        from los.health.checks.base import HealthCheckBase

        append_unique(names, getattr(HealthCheckBase, "celery_queue_name", None))
    except Exception:
        pass
    for item in REQUESTED_QUEUE_FILTERS:
        append_unique(names, item)
    return names


def queue_requested(queue_name, prefix=None):
    if not REQUESTED_QUEUE_FILTERS:
        return True
    candidates = {queue_name}
    if prefix and queue_name.startswith(prefix):
        candidates.add(queue_name[len(prefix) :])
    return bool(candidates.intersection(set(REQUESTED_QUEUE_FILTERS)))


def observe(surface, name, counts):
    total = sum(int(value or 0) for value in counts.values())
    item = {
        "surface": surface,
        "name": name,
        "total": total,
        "counts": counts,
        "full_threshold": FULL_THRESHOLD,
        "is_full_like": total >= FULL_THRESHOLD,
    }
    OBSERVATIONS.append(item)
    return item


def read_sqs_queues():
    try:
        import boto3
        from botocore.config import Config
    except Exception as exc:
        print_compact("queue_depth_check sqs_error", {"stage": "import", "error": safe_error(exc)})
        return

    try:
        region = getattr(settings, "CELERY_BROKER_AWS_REGION", "us-east-2")
        prefix = getattr(settings, "CELERY_BROKER_SQS_QUEUE_NAME_PREFIX", "los-celery-")
        explicit_urls = tuple(getattr(settings, "DJ_CELERY_PANEL_SQS_QUEUE_URLS", ()) or ())
        if isinstance(explicit_urls, str):
            explicit_urls = (explicit_urls,) if explicit_urls.strip() else ()

        client_kwargs = {
            "config": Config(
                retries={
                    "max_attempts": getattr(settings, "DJ_CELERY_PANEL_SQS_MAX_ATTEMPTS", 3),
                    "mode": "standard",
                },
                connect_timeout=getattr(settings, "DJ_CELERY_PANEL_SQS_CONNECT_TIMEOUT", 2.0),
                read_timeout=getattr(settings, "DJ_CELERY_PANEL_SQS_READ_TIMEOUT", 5.0),
            )
        }
        if region:
            client_kwargs["region_name"] = region
        endpoint_url = (
            (getattr(settings, "CELERY_BROKER_SQS_ENDPOINT_URL", None) or "").strip()
            or (os.environ.get("AWS_ENDPOINT_URL") or "").strip()
            or None
        )
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        access_key = getattr(settings, "CELERY_BROKER_AWS_ACCESS_KEY_ID", None)
        secret_key = getattr(settings, "CELERY_BROKER_AWS_SECRET_ACCESS_KEY", None)
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
            session_token = getattr(settings, "CELERY_BROKER_AWS_SESSION_TOKEN", None)
            if session_token:
                client_kwargs["aws_session_token"] = session_token

        sqs = boto3.client("sqs", **client_kwargs)
        urls = list(explicit_urls)
        if not urls:
            paginator = sqs.get_paginator("list_queues")
            params = {"QueueNamePrefix": prefix} if prefix else {}
            for page in paginator.paginate(**params):
                urls.extend(page.get("QueueUrls", []))

        rows = []
        errors = []
        totals = {"visible": 0, "in_flight": 0, "delayed": 0}
        for url in urls:
            queue_name = url.rstrip("/").split("/")[-1]
            if not queue_requested(queue_name, prefix):
                continue
            if len(rows) >= MAX_QUEUES:
                break
            try:
                attrs = sqs.get_queue_attributes(
                    QueueUrl=url,
                    AttributeNames=[
                        "ApproximateNumberOfMessages",
                        "ApproximateNumberOfMessagesNotVisible",
                        "ApproximateNumberOfMessagesDelayed",
                    ],
                ).get("Attributes", {})
                counts = {
                    "visible": int(attrs.get("ApproximateNumberOfMessages") or 0),
                    "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible") or 0),
                    "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed") or 0),
                }
                for key, value in counts.items():
                    totals[key] += value
                rows.append(observe("sqs", queue_name, counts))
            except Exception as exc:
                errors.append({"queue": queue_name, "error": safe_error(exc)})

        print_compact(
            "queue_depth_check sqs_summary",
            {
                "region": region,
                "queue_name_prefix": prefix,
                "configured_url_count": len(explicit_urls),
                "listed_url_count": len(urls),
                "printed_queue_count": len(rows),
                "totals": totals,
                "full_threshold": FULL_THRESHOLD,
                "queues": rows,
                "errors": errors[:MAX_ROWS],
                "truncated": len(rows) >= MAX_QUEUES,
            },
        )
    except Exception as exc:
        print_compact("queue_depth_check sqs_error", {"stage": "read", "error": safe_error(exc)})


def read_redis_queues(queue_names):
    try:
        import redis
    except Exception as exc:
        print_compact("queue_depth_check redis_error", {"stage": "import", "error": safe_error(exc)})
        return

    try:
        broker_url = getattr(settings, "CELERY_BROKER_URL", "") or getattr(settings, "REDIS_URL", "")
        client = redis.Redis.from_url(broker_url)
        rows = []
        for queue_name in queue_names[:MAX_QUEUES]:
            try:
                counts = {"ready": int(client.llen(queue_name) or 0)}
                rows.append(observe("redis", queue_name, counts))
            except Exception as exc:
                rows.append({"surface": "redis", "name": queue_name, "error": safe_error(exc)})
        print_compact(
            "queue_depth_check redis_summary",
            {
                "printed_queue_count": len(rows),
                "queues": rows,
                "full_threshold": FULL_THRESHOLD,
            },
        )
    except Exception as exc:
        print_compact("queue_depth_check redis_error", {"stage": "read", "error": safe_error(exc)})


def read_celery_broker():
    scheme = broker_scheme()
    queue_names = configured_queue_names()
    print_compact(
        "queue_depth_check celery_settings",
        {
            "broker_scheme": scheme,
            "default_queue": getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None),
            "configured_queues": queue_names,
            "requested_queue_filters": REQUESTED_QUEUE_FILTERS,
            "worker_remote_control": getattr(settings, "CELERY_WORKER_ENABLE_REMOTE_CONTROL", None),
            "read_only": True,
        },
    )
    if scheme == "sqs":
        read_sqs_queues()
    elif scheme in ("redis", "rediss", "valkey", "valkeys"):
        read_redis_queues(queue_names)
    else:
        print_compact("queue_depth_check broker_unsupported", {"broker_scheme": scheme, "read_only": True})


def as_text(value):
    if value is None:
        return None
    return str(value)[:120]


def row_for_task_queue(item, field_names, queue_field):
    row = {}
    for field in ["id", "status", queue_field, "created", "modified", "object_pk", "content_type_id"]:
        if field and field in field_names:
            row[field] = as_text(getattr(item, field, None))
    for field in ["policy", "action"]:
        if field in field_names:
            try:
                row[field] = as_text(getattr(item, field, None))
            except Exception:
                pass
    return row


def read_terminator_queue():
    try:
        from terminator.models import TerminatorTaskQueue

        field_names = {field.name for field in TerminatorTaskQueue._meta.get_fields()}
        qs = TerminatorTaskQueue.objects.using("default").all()
        status_counts = []
        open_summary = {}
        oldest_rows = []
        queue_counts = []
        policy_counts = []
        action_counts = []
        queue_field = next((field for field in ["queue_name", "task_queue", "queue"] if field in field_names), None)

        total = qs.count()
        if "status" in field_names:
            status_counts = list(qs.values("status").annotate(count=Count("id")).order_by("-count")[:MAX_ROWS])
            open_qs = qs.filter(status__in=TERMINATOR_OPEN_STATUSES)
        else:
            open_qs = qs.none()

        open_count = open_qs.count()
        now = timezone.now()
        created_field = "created" if "created" in field_names else ("modified" if "modified" in field_names else None)
        if created_field:
            buckets = {}
            for label, minutes in [("older_than_15m", 15), ("older_than_1h", 60), ("older_than_4h", 240), ("older_than_24h", 1440)]:
                buckets[label] = open_qs.filter(**{f"{created_field}__lt": now - timezone.timedelta(minutes=minutes)}).count()
            open_summary["age_buckets"] = buckets
            oldest_qs = open_qs.order_by(created_field)[:MAX_ROWS]
        else:
            oldest_qs = open_qs[:MAX_ROWS]

        for item in oldest_qs:
            oldest_rows.append(row_for_task_queue(item, field_names, queue_field))

        if queue_field:
            queue_counts = list(open_qs.values(queue_field).annotate(count=Count("id")).order_by("-count")[:MAX_ROWS])
        if "policy" in field_names:
            policy_counts = list(open_qs.values("policy__name").annotate(count=Count("id")).order_by("-count")[:MAX_ROWS])
        if "action" in field_names:
            action_counts = list(open_qs.values("action__name").annotate(count=Count("id")).order_by("-count")[:MAX_ROWS])

        observation = observe("terminator_task_queue", "open_statuses", {"open": open_count})
        print_compact(
            "queue_depth_check terminator_summary",
            {
                "model": "terminator.TerminatorTaskQueue",
                "total_rows": total,
                "status_counts": status_counts,
                "open_statuses": TERMINATOR_OPEN_STATUSES,
                "open_count": open_count,
                "open_observation": observation,
                "open_summary": open_summary,
                "queue_field": queue_field,
                "open_counts_by_queue": queue_counts,
                "open_counts_by_policy": policy_counts,
                "open_counts_by_action": action_counts,
                "oldest_open_rows": oldest_rows,
                "read_only": True,
            },
        )
    except Exception as exc:
        print_compact("queue_depth_check terminator_error", {"error": safe_error(exc), "read_only": True})


print_compact("queue_depth_check prod_health", thin_health())
read_celery_broker()
read_terminator_queue()
full_like = [item for item in OBSERVATIONS if item.get("is_full_like")]
nonzero = [item for item in OBSERVATIONS if item.get("total", 0) > 0]
print_compact(
    "queue_depth_check conclusion",
    {
        "full_threshold": FULL_THRESHOLD,
        "full_like_count": len(full_like),
        "full_like_surfaces": full_like[:MAX_ROWS],
        "nonzero_surfaces": nonzero[:MAX_ROWS],
        "read_only": True,
    },
)
"""
    body = (
        template.replace("__PROD_HEALTH__", dump_python(health))
        .replace("__REQUESTED_QUEUE_FILTERS__", dump_python(args.queue or []))
        .replace("__TERMINATOR_OPEN_STATUSES__", dump_python(args.terminator_status))
        .replace("__FULL_THRESHOLD__", str(int(args.full_threshold)))
        .replace("__MAX_QUEUES__", str(int(args.max_queues)))
        .replace("__MAX_ROWS__", str(int(args.max_rows)))
    )
    return textwrap.dedent(body).strip()


def terminator_schema_check_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    template = """
import json

from django.db import connection
from django_tenants.utils import schema_context

TENANT_QUERY = __TENANT_QUERY__
SWEEP_PRODUCTION = __SWEEP_PRODUCTION__
MAX_TENANTS = __MAX_TENANTS__
MAX_ROWS = __MAX_ROWS__


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def safe_error(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:300]}


def fetch_migration_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name, applied FROM django_migrations WHERE app = %s ORDER BY applied DESC, name DESC LIMIT %s",
            ["terminator", MAX_ROWS],
        )
        return [{"name": row[0], "applied": row[1]} for row in cursor.fetchall()]


def fetch_table_count():
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM terminator_terminatortaskqueuesettings")
        return int(cursor.fetchone()[0])


def inspect_schema(row, is_target=False):
    schema_name = row.get("schema_name")
    result = {
        "name": row.get("name"),
        "schema_name": schema_name,
        "domains": (row.get("domains") or [])[:2],
        "in_production": row.get("in_production"),
        "is_target": is_target,
        "read_only": True,
    }
    try:
        with schema_context(schema_name):
            # The incident is a schema drift problem. Checking to_regclass first
            # keeps the script read-only and avoids importing application code
            # that may query the missing table as a side effect.
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass(%s)", ["terminator_terminatortaskqueuesettings"])
                result["table_present"] = bool(cursor.fetchone()[0])

            migrations = fetch_migration_rows()
            result["terminator_migration_count"] = len(migrations)
            result["latest_terminator_migrations"] = migrations[:MAX_ROWS]
            if result["table_present"]:
                result["settings_row_count"] = fetch_table_count()
            else:
                result["settings_row_count"] = None
    except Exception as exc:
        result["error"] = safe_error(exc)
    return result


print_json("terminator_schema_check prod_health", thin_health())
target = resolve_tenant(TENANT_QUERY)
target_result = inspect_schema(target, is_target=True)
print_compact("terminator_schema_check target", target_result)

sweep_results = []
if SWEEP_PRODUCTION:
    rows = [
        row
        for row in load_tenant_rows()
        if row.get("schema_name") != target.get("schema_name") and row.get("in_production") is not False
    ]
    for row in rows[:MAX_TENANTS]:
        sweep_results.append(inspect_schema(row))
    missing = [row for row in sweep_results if row.get("table_present") is False]
    errors = [row for row in sweep_results if row.get("error")]
    print_compact(
        "terminator_schema_check production_sweep",
        {
            "checked_count": len(sweep_results),
            "max_tenants": MAX_TENANTS,
            "missing_table_count": len(missing),
            "missing_tables": [
                {
                    "name": row.get("name"),
                    "schema_name": row.get("schema_name"),
                    "terminator_migration_count": row.get("terminator_migration_count"),
                }
                for row in missing[:MAX_ROWS]
            ],
            "error_count": len(errors),
            "errors": [
                {"name": row.get("name"), "schema_name": row.get("schema_name"), "error": row.get("error")}
                for row in errors[:MAX_ROWS]
            ],
            "truncated": len(rows) > MAX_TENANTS,
            "read_only": True,
        },
    )

target_missing = target_result.get("table_present") is False
target_error = bool(target_result.get("error"))
print_compact(
    "terminator_schema_check conclusion",
    {
        "target_schema": target_result.get("schema_name"),
        "target_table_present": target_result.get("table_present"),
        "target_missing_table": target_missing,
        "target_error": target_error,
        "sweep_enabled": SWEEP_PRODUCTION,
        "recommended_next_step": (
            "apply tenant terminator migration for target schema, then rerun this script"
            if target_missing
            else "no target table gap detected by this read-only check"
        ),
        "mutation_included": False,
        "read_only": True,
    },
)
"""
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__SWEEP_PRODUCTION__", str(bool(args.sweep_production)))
        .replace("__MAX_TENANTS__", str(int(args.max_tenants)))
        .replace("__MAX_ROWS__", str(int(args.max_rows)))
    )
    return textwrap.dedent(body).strip()


def approval_worksheet_boarding_body(args: argparse.Namespace, *, repair_plan: bool) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    return textwrap.dedent(
        shared_tenant_helpers(aliases, health)
        + f"""
from django.db.models import Q

TENANT_QUERY = {dump_python(args.tenant)}
APPLICATION_NUMBER = {int(args.application_number)}
LOAN_NUMBER = {dump_python(args.loan_number)}
BUSINESS_NAME = {dump_python(args.business_name)}
MAX_TASK_ROWS = {int(args.max_task_rows)}
MAX_AGGREGATOR_ROWS = {int(args.max_aggregator_rows)}
REPAIR_PLAN_MODE = {bool(repair_plan)}
SUMMARY_ONLY = {not bool(args.include_details)}
"""
        + r'''
WATCH_TASK_NAMES = {
    "LOAN_APPROVAL",
    "DOC_PREP",
    "POST_APPROVAL_CHECK",
    "PRE_CLOSING_DOCUMENT",
    "CLOSING_DOCUMENTS",
    "CLOSING_FULFILLMENT",
    "FUNDING",
    "BOARDING",
    "BOARDING_UPDATE",
}


def trim(value, limit=240):
    if value in (None, ""):
        return value
    text = str(value).replace("\\n", " ")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def status_label(status):
    from los.backoffice.models import TaskExecution

    try:
        return dict(TaskExecution.STATUS_CHOICES).get(status, status)
    except Exception:
        return status


def task_map_row(task_map):
    if not task_map:
        return None
    return {
        "name": task_map.name,
        "sub_task": task_map.sub_task,
        "sub_task_type": task_map.sub_task_type,
    }


def task_row(task):
    creator = getattr(task, "creator_task", None)
    actor = getattr(task, "actor", None)
    actor_label = None
    if actor:
        actor_label = getattr(actor, "username", None) or getattr(actor, "email", None)
    return {
        "id": task.id,
        "slug": str(getattr(task, "slug", "")),
        "task_map": task_map_row(task.task_map),
        "status": task.get_status_display(),
        "status_id": task.status,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "is_manual": getattr(task, "is_manual", None),
        "task_type": task.task_type,
        "level": task.level,
        "actor": actor_label,
        "created": task.created,
        "modified": task.modified,
        "action_taken_at": task.action_taken_at,
        "completion_date": getattr(task, "completion_date", None),
        "allowed_operations": (task.allowed_operations or [])[:8],
        "internal_remarks": trim(task.internal_remarks),
        "status_reason": trim(getattr(task, "status_reason", None)),
        "error": trim(task.error),
        "creator_task": {
            "id": creator.id,
            "task_map": task_map_row(creator.task_map),
            "status": creator.get_status_display(),
        }
        if creator
        else None,
    }


def compact_doc(doc):
    doc_type = doc.document_type
    return {
        "id": str(doc.id),
        "name": doc.name,
        "document_type": {
            "id": doc_type.id,
            "name": doc_type.name,
            "label": doc_type.label,
            "bucket": doc_type.bucket,
        },
        "status": doc.status,
        "source": doc.source,
        "visibility": doc.visibility,
        "created": doc.created,
        "modified": doc.modified,
        "document_present": bool(doc.document),
        "document_template_id": doc.document_template_id,
        "created_by": getattr(doc.created_by, "username", None) or getattr(doc.created_by, "email", None),
    }


def summarize_step(value):
    if not isinstance(value, dict):
        return trim(value)

    selected = {}
    for key in [
        "result",
        "status",
        "apiSuccess",
        "api_success",
        "success",
        "loan_number",
        "account_number",
        "external_loan_id",
        "message",
        "error",
        "error_message",
    ]:
        if key in value:
            selected[key] = trim(value.get(key))
    selected["keys"] = sorted(str(k) for k in value.keys())[:25]
    if len(value.keys()) > 25:
        selected["keys_truncated"] = len(value.keys()) - 25
    return selected


def summarize_core_response(response):
    if not isinstance(response, dict):
        return {"type": type(response).__name__, "value": trim(response)}
    watched = [
        "search_account",
        "create_customer",
        "create_loan",
        "create_custom_fields",
        "create_payments_account",
        "centerdoc_upload",
    ]
    return {
        "keys": sorted(str(k) for k in response.keys())[:40],
        "selected_steps": {key: summarize_step(response.get(key)) for key in watched if key in response},
        "raw_payload_omitted": True,
    }


def aggregator_row(aggregator):
    details = aggregator.sub_task_details or []
    last_details = []
    for item in details[-4:]:
        task_map = item.get("task_map") or {}
        last_details.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "task_map": {
                    "name": task_map.get("name"),
                    "sub_task": task_map.get("sub_task"),
                    "sub_task_type": task_map.get("sub_task_type"),
                },
                "is_workflow_end": item.get("is_workflow_end"),
                "next_task_name": item.get("next_task_name"),
                "creator_task_name": item.get("creator_task_name"),
                "created": item.get("created"),
                "action_taken_at": item.get("action_taken_at"),
            }
        )
    return {
        "id": aggregator.id,
        "task_name": aggregator.task_name,
        "task_id": aggregator.task_id,
        "status": status_label(aggregator.status),
        "status_id": aggregator.status,
        "stage": aggregator.stage,
        "display_order": aggregator.display_order,
        "sub_task_count": len(details),
        "last_sub_tasks": last_details,
    }


def find_loans():
    from los.requests.models import Loan

    query = Q(application_number=APPLICATION_NUMBER)
    if LOAN_NUMBER:
        query |= Q(loan_number=str(LOAN_NUMBER))
    if BUSINESS_NAME:
        query |= Q(borrower_name__icontains=BUSINESS_NAME)

    return list(
        Loan.objects.select_related("current_task__task_map", "request_status", "product")
        .filter(query)
        .order_by("-modified")[:5]
    )


def loan_summary(loan):
    status = loan.request_status
    return {
        "id": str(loan.id),
        "application_number": loan.application_number,
        "loan_number": loan.loan_number,
        "borrower_name": loan.borrower_name,
        "product": getattr(loan.product, "name", None),
        "request_status": {
            "id": status.id if status else None,
            "code": status.code if status else None,
            "phase": status.phase if status else None,
            "status": status.status if status else None,
            "terminal_status": status.terminal_status if status else None,
        },
        "current_task": task_row(loan.current_task) if loan.current_task_id else None,
        "is_credit_card_loan": getattr(loan, "is_credit_card_loan", None),
        "details_keys": sorted((loan.details or {}).keys())[:40],
        "backoffice_task_status_keys": sorted((loan.backoffice_task_status or {}).keys())[:40],
        "core_integration_response": summarize_core_response(loan.core_integration_response or {}),
    }


def current_task_brief(task):
    if not task:
        return None
    task_map = task.task_map
    return {
        "id": task.id,
        "task_map": {
            "name": task_map.name if task_map else None,
            "sub_task": task_map.sub_task if task_map else None,
            "sub_task_type": task_map.sub_task_type if task_map else None,
        },
        "status": task.get_status_display(),
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "created": task.created,
        "modified": task.modified,
    }


def loan_decision_summary(loan, classification):
    status = loan.request_status
    return {
        "loan": {
            "id": str(loan.id),
            "application_number": loan.application_number,
            "loan_number": loan.loan_number,
            "borrower_name": loan.borrower_name,
            "product": getattr(loan.product, "name", None),
        },
        "request_status": {
            "code": status.code if status else None,
            "phase": status.phase if status else None,
            "status": status.status if status else None,
            "terminal_status": status.terminal_status if status else None,
        },
        "current_task": current_task_brief(loan.current_task) if loan.current_task_id else None,
        "classification": classification,
    }


def approval_docs_for(loan):
    q = (
        Q(document_type__name__iexact="approval_worksheet")
        | Q(document_type__label__icontains="Approval Worksheet")
        | Q(name__icontains="approval_worksheet")
        | Q(name__icontains="Approval_Worksheet")
        | Q(description__icontains="approval_worksheet")
    )
    return list(
        loan.documents.select_related("document_type", "created_by", "document_template")
        .filter(q)
        .order_by("-created")[:12]
    )


def task_sets_for(loan):
    from los.backoffice.models import TaskExecution

    tasks = list(
        TaskExecution.objects.select_related("task_map", "creator_task__task_map", "actor")
        .filter(entity=loan)
        .order_by("-created")[:250]
    )
    interesting = []
    for task in tasks:
        name = task.task_map.name if task.task_map else None
        if name in WATCH_TASK_NAMES:
            interesting.append(task)
        if len(interesting) >= MAX_TASK_ROWS:
            break
    current_by_name = {}
    for task in tasks:
        name = task.task_map.name if task.task_map else None
        if name and name not in current_by_name and task.is_latest and task.is_valid:
            current_by_name[name] = task
    return tasks, interesting, current_by_name


def aggregators_for(loan):
    from los.requests.models import LoanTaskAggregator

    return list(
        LoanTaskAggregator.objects.filter(loan=loan, is_valid=True)
        .order_by("display_order", "id")[:MAX_AGGREGATOR_ROWS]
    )


def classify(loan, tasks, docs):
    from los.backoffice.models import TaskExecution, TaskMap

    terminal = TaskExecution.terminal_statuses()
    current = loan.current_task
    current_name = current.task_map.name if current and current.task_map else None
    current_status_terminal = bool(current and current.status in terminal)
    create_loan = (loan.core_integration_response or {}).get("create_loan")
    create_loan_success = isinstance(create_loan, dict) and str(create_loan.get("result", "")).lower() == "success"

    closing_signed = [
        task
        for task in tasks
        if task.task_map
        and task.task_map.name == TaskMap.TASK_CLOSING_FULFILLMENT
        and task.task_map.sub_task == TaskMap.SUB_TASK_REVIEW
        and task.task_map.sub_task_type == TaskMap.SUB_TASK_TYPE_SIGNED_DOCUMENTS
    ]
    closing_signed_terminal = [task for task in closing_signed if task.status in terminal]
    boarding_terminal = [
        task
        for task in tasks
        if task.task_map and task.task_map.name in {TaskMap.TASK_BOARDING, TaskMap.TASK_BOARDING_UPDATE} and task.status in terminal
    ]

    hints = []
    if docs:
        hints.append("approval_worksheet_exists_in_los")
    if current_name == TaskMap.TASK_DOC_PREP and not current_status_terminal and not closing_signed_terminal:
        hints.append("los_current_task_is_active_doc_prep_no_closing_signed_docs_terminal")
    if not docs and closing_signed_terminal:
        hints.append("closing_signed_docs_terminal_but_approval_worksheet_missing")
    if create_loan_success and current_name == TaskMap.TASK_DOC_PREP:
        hints.append("ventures_create_loan_success_conflicts_with_los_doc_prep_current_task")
    if create_loan_success and not boarding_terminal:
        hints.append("core_create_loan_success_but_no_terminal_boarding_task_found")
    if boarding_terminal and not docs:
        hints.append("terminal_boarding_seen_but_approval_worksheet_missing")

    return {
        "current_task_name": current_name,
        "current_task_terminal": current_status_terminal,
        "approval_doc_count": len(docs),
        "closing_signed_docs_task_count": len(closing_signed),
        "closing_signed_docs_terminal_count": len(closing_signed_terminal),
        "boarding_terminal_count": len(boarding_terminal),
        "create_loan_success": create_loan_success,
        "hints": hints,
        "candidate_closing_signed_terminal_task_ids": [task.id for task in closing_signed_terminal[:5]],
        "candidate_boarding_terminal_task_ids": [task.id for task in boarding_terminal[:5]],
    }


def build_repair_plan(loan, classification):
    plan = []
    if classification["approval_doc_count"]:
        plan.append(
            {
                "name": "no_document_repair_needed",
                "recommended": True,
                "reason": "At least one approval worksheet document row already exists in LOS.",
            }
        )
    elif classification["closing_signed_docs_terminal_count"]:
        plan.append(
            {
                "name": "approval_worksheet_regeneration_candidate",
                "recommended": True,
                "mutation_included": False,
                "preconditions": [
                    "approval worksheet document count is zero",
                    "closing fulfillment signed-documents task has a terminal row",
                    "operator confirms the exact loan id and task id from this output",
                ],
                "next_script_after_approval": (
                    "generate a guarded script that rechecks count=0, instantiates "
                    "CLOSING_FULFILLMENT(task_execution_instance=<signed_docs_task>), "
                    "calls generate_approval_worksheet(), and prints before/after counts"
                ),
                "target_loan_id": str(loan.id),
                "candidate_task_ids": classification["candidate_closing_signed_terminal_task_ids"],
            }
        )
    elif classification["current_task_name"] == "DOC_PREP":
        plan.append(
            {
                "name": "do_not_generate_worksheet_yet",
                "recommended": True,
                "mutation_included": False,
                "reason": (
                    "Production code generates the legacy Approval Worksheet from closing "
                    "fulfillment signed-documents acceptance, but LOS still has DOC_PREP as current task."
                ),
                "next_action": (
                    "Use this diagnostic output to determine why DOC_PREP did not advance. "
                    "If the business wants LOS workflow reconciled to Ventures, prepare a separate "
                    "approval-gated workflow/task repair after identifying the missing transition."
                ),
            }
        )
    else:
        plan.append(
            {
                "name": "insufficient_preconditions_for_safe_repair",
                "recommended": True,
                "mutation_included": False,
                "reason": "The diagnostic did not prove a safe single-row document regeneration or workflow repair.",
            }
        )

    if classification["create_loan_success"] and classification["current_task_name"] == "DOC_PREP":
        plan.append(
            {
                "name": "ventures_los_state_mismatch",
                "recommended": True,
                "mutation_included": False,
                "reason": (
                    "LOS core_integration_response has create_loan success while current task is DOC_PREP. "
                    "That points to workflow state reconciliation, not just missing document generation."
                ),
            }
        )

    return plan


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)

with schema_context(tenant["schema_name"]):
    print(f"schema={tenant['schema_name']}")
    loans = find_loans()
    print(f"loan_match_count={len(loans)}")
    if not loans:
        print_json(
            "no_loan_found",
            {
                "application_number": APPLICATION_NUMBER,
                "loan_number": LOAN_NUMBER,
                "business_name": BUSINESS_NAME,
            },
        )
        raise SystemExit(2)

    for idx, loan in enumerate(loans, start=1):
        docs = approval_docs_for(loan)
        tasks, interesting_tasks, current_by_name = task_sets_for(loan)
        classification = classify(loan, tasks, docs)
        print_json(f"loan_{idx}_decision_summary", loan_decision_summary(loan, classification))
        print_json(f"loan_{idx}_classification", classification)

        if REPAIR_PLAN_MODE:
            print_json(f"loan_{idx}_dry_run_repair_plan", build_repair_plan(loan, classification))
        else:
            print("repair_plan_omitted=true")
            print("rerun_generator_with=approval-worksheet-repair-plan after reviewing classification")

        if SUMMARY_ONLY:
            print("details_omitted=true")
            print("rerun_generator_with=approval-worksheet-investigation --include-details only if task rows are needed")
            continue

        aggregators = aggregators_for(loan)
        print_json(f"loan_{idx}_full_summary", loan_summary(loan))
        print_json(f"loan_{idx}_approval_worksheet_documents", [compact_doc(doc) for doc in docs])
        print_json(f"loan_{idx}_interesting_task_history", [task_row(task) for task in interesting_tasks])
        print_json(
            f"loan_{idx}_current_valid_tasks_by_name",
            {name: task_row(task) for name, task in sorted(current_by_name.items()) if name in WATCH_TASK_NAMES},
        )
        print_json(f"loan_{idx}_task_aggregators", [aggregator_row(item) for item in aggregators])
'''
    ).strip()


def doc_prep_progression_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    template = r'''
from django.db.models import Count, Q

TENANT_QUERY = __TENANT_QUERY__
APPLICATION_NUMBER = __APPLICATION_NUMBER__
TASK_ID = __TASK_ID__
BUSINESS_NAME = __BUSINESS_NAME__


def trim(value, limit=220):
    if value in (None, ""):
        return value
    text = str(value).replace("\\n", " ")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def exc_summary(exc):
    return {
        "type": type(exc).__name__,
        "message": trim(exc),
    }


def task_map_row(task_map):
    if not task_map:
        return None
    return {
        "name": task_map.name,
        "sub_task": task_map.sub_task,
        "sub_task_type": task_map.sub_task_type,
    }


def task_brief(task):
    actor = getattr(task, "actor", None)
    return {
        "id": task.id,
        "task_map": task_map_row(task.task_map),
        "status": task.get_status_display(),
        "status_id": task.status,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "is_active": getattr(task, "is_active", None),
        "is_manual": task.is_manual,
        "task_type": task.task_type,
        "level": task.level,
        "actor": getattr(actor, "username", None) or getattr(actor, "email", None) if actor else None,
        "created": task.created,
        "modified": task.modified,
        "action_taken_at": task.action_taken_at,
        "allowed_operations": task.allowed_operations or [],
        "actions": sorted((task.actions or {}).keys()),
        "internal_remarks": trim(task.internal_remarks),
        "status_reason": trim(getattr(task, "status_reason", None)),
        "error": trim(task.error),
        "creator_task": {
            "id": task.creator_task_id,
            "task_map": task_map_row(task.creator_task.task_map) if task.creator_task_id else None,
            "status": task.creator_task.get_status_display() if task.creator_task_id else None,
        }
        if task.creator_task_id
        else None,
    }


def loan_brief(loan):
    status = loan.request_status
    return {
        "id": str(loan.id),
        "application_number": loan.application_number,
        "loan_number": loan.loan_number,
        "borrower_name": loan.borrower_name,
        "product": getattr(loan.product, "name", None),
        "is_sba_product": getattr(loan.product, "is_sba_product", None),
        "request_status": {
            "code": status.code if status else None,
            "phase": status.phase if status else None,
            "status": status.status if status else None,
            "terminal_status": status.terminal_status if status else None,
        },
        "current_task_id": loan.current_task_id,
        "closing_date": getattr(loan, "closing_date", None),
        "is_closing_date_less_than_today": getattr(loan, "is_closing_date_less_than_today", None),
        "loan_number_present": bool(loan.loan_number),
        "core_integration_response_keys": sorted((loan.core_integration_response or {}).keys()),
    }


def selected_core_steps(loan):
    response = loan.core_integration_response or {}
    selected = {}
    for key in [
        "search_account",
        "create_customer",
        "create_loan",
        "create_custom_fields",
        "create_payments_account",
        "centerdoc_upload",
    ]:
        value = response.get(key)
        if isinstance(value, dict):
            selected[key] = {
                "result": value.get("result"),
                "status": value.get("status"),
                "apiSuccess": value.get("apiSuccess"),
                "success": value.get("success"),
                "loan_number": value.get("loan_number"),
                "account_number": value.get("account_number"),
                "message": trim(value.get("message")),
                "error": trim(value.get("error") or value.get("error_message")),
                "keys": sorted(str(k) for k in value.keys())[:20],
            }
        elif value is not None:
            selected[key] = trim(value)
    return selected


def status_counts(qs):
    return [
        {"status": row["status"], "count": row["count"]}
        for row in qs.values("status").annotate(count=Count("id")).order_by("status")
    ]


def doc_prep_blocker_checks(loan, task):
    from config.exceptions import CustomError
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.managers.conditions import ConditionsManager
    from los.requests.managers.underwriting_v2 import UnderwritingV2Manager
    from los.requests.models import Collateral

    checks = []

    def add_check(name, ok, **extra):
        payload = {"name": name, "ok": ok}
        payload.update(extra)
        checks.append(payload)

    if loan.product and loan.product.is_sba_product:
        try:
            UnderwritingV2Manager(loan).validate_approved_amount()
            add_check("sba_approved_amount_validation", True)
        except Exception as exc:
            add_check("sba_approved_amount_validation", False, exception=exc_summary(exc))
    else:
        add_check("sba_approved_amount_validation", True, skipped=True)

    try:
        ConditionsManager(loan).validate_if_conditions_at_terminal_status()
        add_check("conditions_terminal_validation", True)
    except Exception as exc:
        add_check("conditions_terminal_validation", False, exception=exc_summary(exc))

    add_check(
        "closing_date_not_past",
        not bool(getattr(loan, "is_closing_date_less_than_today", False)),
        closing_date=getattr(loan, "closing_date", None),
    )

    collaterals = list(
        Collateral.objects.filter(
            Q(Q(loan=loan) | Q(relation__loan=loan)) & Q(is_insurance_required=True)
        ).order_by("id")[:25]
    )
    missing_insurance = []
    for collateral in collaterals:
        if not collateral.insurance_set.exists():
            missing_insurance.append(
                {
                    "id": str(collateral.id),
                    "description": trim(getattr(collateral, "description", None)),
                    "collateral_type": trim(getattr(collateral, "collateral_type", None)),
                }
            )
    add_check(
        "insurance_required_collaterals_have_insurance",
        not bool(missing_insurance),
        required_collateral_count=len(collaterals),
        missing_insurance=missing_insurance[:8],
        missing_insurance_truncated=max(len(missing_insurance) - 8, 0),
    )

    inflight_statuses = TaskExecution.inflight_statuses()
    pending_task_specs = [
        ("appraisal_pending", TaskMap.TASK_APPRAISAL_AND_ENVIRONMENTAL_REVIEW, None, None),
        ("irs_tax_returns_pending", TaskMap.TASK_IRS_TAX_RETURN, None, None),
        ("credit_memo_review_incomplete", TaskMap.TASK_CREDIT_MEMO, TaskMap.SUB_TASK_REVIEW, None),
        ("flood_search_review_pending", TaskMap.TASK_FLOOD_SEARCH, TaskMap.SUB_TASK_REVIEW, None),
    ]
    for name, task_name, sub_task, sub_task_type in pending_task_specs:
        qs = loan.taskexecution_set.filter(
            task_map__name=task_name,
            is_latest=True,
            is_valid=True,
            status__in=inflight_statuses,
        )
        if sub_task:
            qs = qs.filter(task_map__sub_task=sub_task)
        if sub_task_type:
            qs = qs.filter(task_map__sub_task_type=sub_task_type)
        rows = list(qs.select_related("task_map").order_by("-created")[:5])
        add_check(
            name,
            not bool(rows),
            count=len(rows),
            rows=[task_brief(row) for row in rows],
        )

    return checks


def related_state(loan):
    from los.backoffice.models import TaskExecution, TaskMap
    from los.workflows.constants import LOAN_CONDITION_REQUEST

    interesting_names = [
        TaskMap.TASK_DOC_PREP,
        TaskMap.TASK_PRE_CLOSING_DOCUMENT,
        TaskMap.TASK_CLOSING_DOCUMENTS,
        TaskMap.TASK_CLOSING_FULFILLMENT,
        TaskMap.TASK_FUNDING,
        TaskMap.TASK_BOARDING,
        TaskMap.TASK_BOARDING_UPDATE,
    ]
    latest = []
    for task in (
        loan.taskexecution_set.select_related("task_map", "creator_task__task_map", "actor")
        .filter(task_map__name__in=interesting_names, is_latest=True, is_valid=True)
        .order_by("task_map__name", "-created")
    ):
        latest.append(task_brief(task))

    condition_counts = status_counts(loan.conditions.all())
    open_condition_srs = []
    for sr in loan.servicerequest_set.select_related("task_workflow", "request_status").filter(
        task_workflow__name=LOAN_CONDITION_REQUEST,
        request_status__terminal_status=False,
    )[:8]:
        open_condition_srs.append(
            {
                "id": str(sr.id),
                "workflow": sr.task_workflow.name if sr.task_workflow_id else None,
                "status": sr.request_status.status if sr.request_status_id else None,
                "phase": sr.request_status.phase if sr.request_status_id else None,
                "created": sr.created,
                "modified": sr.modified,
            }
        )

    return {
        "latest_relevant_tasks": latest,
        "condition_counts": condition_counts,
        "open_condition_service_requests": open_condition_srs,
        "selected_core_integration_steps": selected_core_steps(loan),
    }


def classify(checks, loan, task):
    blockers = [check for check in checks if not check.get("ok")]
    actions = set((task.actions or {}).keys())
    allowed_operations = set(task.allowed_operations or [])
    progression_actions = actions & {"send_to_next_level", "accept", "submit"}
    hint = None
    if blockers:
        hint = "doc_prep_validation_blockers_present"
    elif not progression_actions:
        hint = "doc_prep_task_in_progress_but_no_progression_action_key_visible"
    elif task.id != loan.current_task_id:
        hint = "task_is_not_current_task"
    else:
        hint = "doc_prep_appears_waiting_for_manual_progression_action"
    return {
        "hint": hint,
        "blocker_count": len(blockers),
        "blockers": [
            {
                "name": item.get("name"),
                "exception": item.get("exception"),
                "count": item.get("count"),
                "missing_insurance": item.get("missing_insurance"),
            }
            for item in blockers
        ],
        "visible_progression_actions": sorted(progression_actions),
        "allowed_operations_count": len(allowed_operations),
        "recommended_next_step": (
            "resolve listed validation blockers before trying to advance Doc Prep"
            if blockers
            else (
                "inspect task action config or UI permissions because no progression action key is visible"
                if not progression_actions
                else "have an authorized lender user advance Doc Prep; do not generate Approval Worksheet until downstream closing task exists"
            )
        ),
        "mutation_included": False,
    }


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)
with schema_context(tenant["schema_name"]):
    from los.backoffice.models import TaskExecution
    from los.requests.models import Loan

    loan = Loan.objects.select_related("current_task__task_map", "request_status", "product").get(
        application_number=APPLICATION_NUMBER
    )
    task = TaskExecution.objects.select_related("task_map", "creator_task__task_map", "actor").get(id=TASK_ID)

    checks = doc_prep_blocker_checks(loan, task)
    classification = classify(checks, loan, task)

    print_json("doc_prep_progression_summary", {
        "schema": tenant["schema_name"],
        "loan": loan_brief(loan),
        "target_task": task_brief(task),
        "checks": checks,
        "classification": classification,
    })
    print_json("doc_prep_related_state", related_state(loan))
'''
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_NUMBER__", str(int(args.application_number)))
        .replace("__TASK_ID__", str(int(args.task_id)))
        .replace("__BUSINESS_NAME__", dump_python(args.business_name))
    )
    return textwrap.dedent(body).strip()


def doc_prep_closing_date_repair_plan_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    template = r'''
import datetime

from django.utils import timezone

from los.requests.utils import get_time_zone

TENANT_QUERY = __TENANT_QUERY__
APPLICATION_NUMBER = __APPLICATION_NUMBER__
TASK_ID = __TASK_ID__
BUSINESS_NAME = __BUSINESS_NAME__
PROPOSED_CLOSING_DATE = __PROPOSED_CLOSING_DATE__


def trim(value, limit=220):
    if value in (None, ""):
        return value
    text = str(value).replace("\\n", " ")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def exc_summary(exc):
    return {
        "type": type(exc).__name__,
        "message": trim(exc),
    }


def parse_proposed_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        print_json("invalid_proposed_closing_date", {"value": value, "error": str(exc)})
        raise SystemExit(2)


def task_map_row(task_map):
    if not task_map:
        return None
    return {
        "name": task_map.name,
        "sub_task": task_map.sub_task,
        "sub_task_type": task_map.sub_task_type,
        "task_version": task_map.task_version,
    }


def actor_name(actor):
    if not actor:
        return None
    return getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)


def task_brief(task):
    if not task:
        return None
    return {
        "id": task.id,
        "task_map": task_map_row(task.task_map if task.task_map_id else None),
        "status": task.get_status_display(),
        "status_id": task.status,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "is_active": getattr(task, "is_active", None),
        "actor": actor_name(task.actor),
        "actions": sorted((task.actions or {}).keys()),
        "allowed_operations": task.allowed_operations or [],
        "error": trim(task.error),
        "remarks": trim(getattr(task, "remarks", None)),
        "internal_remarks": trim(task.internal_remarks),
        "created": task.created,
        "modified": task.modified,
        "action_taken_at": task.action_taken_at,
    }


def approval_brief(approval):
    if not approval:
        return None
    return {
        "id": str(approval.id),
        "approved_term": getattr(approval, "approved_term", None),
        "approved_first_payment_date": getattr(approval, "approved_first_payment_date", None),
        "created": getattr(approval, "created", None),
        "modified": getattr(approval, "modified", None),
    }


def projected_dates(loan, proposed_date):
    if not proposed_date:
        return None
    original_closing_date = loan.closing_date
    loan.closing_date = proposed_date
    try:
        approval = loan.approvals.first()
        payment_start_date = None
        maturity_date = None
        advance_expiration_date = None
        errors = {}
        try:
            payment_start_date = loan.calculate_payment_start_date(proposed_date)
        except Exception as exc:
            errors["payment_start_date"] = exc_summary(exc)
        try:
            maturity_date = loan.calculate_maturity_date(approval)
        except Exception as exc:
            errors["maturity_date"] = exc_summary(exc)
        try:
            advance_expiration_date = loan.calculate_advance_expiration_date()
        except Exception as exc:
            errors["advance_expiration_date"] = exc_summary(exc)
        return {
            "payment_start_date": payment_start_date,
            "maturity_date": maturity_date,
            "advance_expiration_date": advance_expiration_date,
            "projection_errors": errors,
            "note": "calculated in memory only; no save performed",
        }
    finally:
        loan.closing_date = original_closing_date


def validate_proposed_date(loan, proposed_date):
    if not proposed_date:
        return {
            "provided": False,
            "valid": None,
            "message": "No proposed closing date supplied. Get a business-approved current/future closing date before any data repair.",
        }
    from los.requests.validators import LoanValidator

    try:
        LoanValidator(loan=loan).validate_closing_date(proposed_date)
        return {"provided": True, "valid": True, "proposed_closing_date": proposed_date}
    except Exception as exc:
        return {
            "provided": True,
            "valid": False,
            "proposed_closing_date": proposed_date,
            "exception": exc_summary(exc),
        }


def loan_state(loan, task, proposed_date):
    today = timezone.localdate(timezone=get_time_zone())
    approval = loan.approvals.order_by("-created").first()
    closing_date = loan.closing_date
    return {
        "loan": {
            "id": str(loan.id),
            "application_number": loan.application_number,
            "loan_number": loan.loan_number,
            "borrower_name": loan.borrower_name,
            "product": getattr(loan.product, "name", None),
            "request_status": {
                "code": loan.request_status.code if loan.request_status_id else None,
                "phase": loan.request_status.phase if loan.request_status_id else None,
                "status": loan.request_status.status if loan.request_status_id else None,
                "terminal_status": loan.request_status.terminal_status if loan.request_status_id else None,
            },
            "current_task_id": loan.current_task_id,
            "closing_date": closing_date,
            "local_today": today,
            "days_stale": (today - closing_date).days if closing_date else None,
            "is_closing_date_less_than_today": getattr(loan, "is_closing_date_less_than_today", None),
            "maturity_date": getattr(loan, "maturity_date", None),
            "advance_expiration_date": getattr(loan, "advance_expiration_date", None),
            "payment_start_date": getattr(loan, "payment_start_date", None),
        },
        "target_task": task_brief(task),
        "approval": approval_brief(approval),
        "proposed_date_validation": validate_proposed_date(loan, proposed_date),
        "projected_dates_if_proposed": projected_dates(loan, proposed_date),
    }


def build_plan(loan, task, proposed_date):
    stale_closing_date = bool(getattr(loan, "is_closing_date_less_than_today", False))
    validation = validate_proposed_date(loan, proposed_date)
    actions = set((task.actions or {}).keys())
    plan = [
        {
            "name": "root_cause",
            "recommended": True,
            "mutation_included": False,
            "summary": "Doc Prep cannot advance because closing_date is before the tenant-local current date.",
            "evidence": {
                "closing_date": loan.closing_date,
                "is_closing_date_less_than_today": stale_closing_date,
                "visible_progression_actions": sorted(actions & {"accept", "send_to_next_level", "submit"}),
            },
        },
        {
            "name": "preferred_fix",
            "recommended": True,
            "mutation_included": False,
            "summary": "Have an authorized lender/backoffice user update Doc Prep closing details to the business-approved current/future closing date, then advance Doc Prep through the UI.",
            "reason": "The UI/API path owns related date recalculation and keeps task/audit behavior normal.",
        },
        {
            "name": "argo_data_repair_candidate_after_approval",
            "recommended": bool(validation.get("valid")),
            "mutation_included": False,
            "preconditions": [
                "operator confirms tenant schema encore and loan id from this output",
                "operator provides and approves the exact proposed_closing_date",
                "proposed_closing_date passes LoanValidator.validate_closing_date",
                "current task is still the same active DOC_PREP task",
                "business accepts recalculated payment/maturity/advance-expiration dates",
            ],
            "proposed_write_set": (
                [
                    "Loan.closing_date",
                    "LoanApproval.approved_first_payment_date when approval exists",
                    "Loan.maturity_date when recalculated",
                    "Loan.advance_expiration_date when recalculated",
                ]
                if validation.get("valid")
                else []
            ),
            "next_script_after_approval": (
                "generate a guarded mutation script that rechecks these preconditions, validates the proposed date again, "
                "prints before/after values, and saves only the approved date fields"
            ),
        },
    ]
    if not validation.get("provided"):
        plan.append(
            {
                "name": "missing_business_date",
                "recommended": True,
                "mutation_included": False,
                "next_action": "Ask business/ops for the actual closing date to use; do not default this to today without approval.",
            }
        )
    elif validation.get("valid") is False:
        plan.append(
            {
                "name": "proposed_date_rejected",
                "recommended": True,
                "mutation_included": False,
                "next_action": "Choose a different business-approved closing date that passes validation before repair.",
                "validation": validation,
            }
        )
    return plan


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)
proposed_date = parse_proposed_date(PROPOSED_CLOSING_DATE)

with schema_context(tenant["schema_name"]):
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.models import Loan

    loan = Loan.objects.select_related("current_task__task_map", "request_status", "product").get(
        application_number=APPLICATION_NUMBER
    )
    task = TaskExecution.objects.select_related("task_map", "actor").get(id=TASK_ID)

    if task.entity_id != loan.id:
        print_json("target_mismatch", {
            "loan_id": str(loan.id),
            "task_entity_id": str(task.entity_id),
            "task_id": task.id,
            "mutation_included": False,
        })
        raise SystemExit(2)

    if not (
        task.task_map_id
        and task.task_map.name == TaskMap.TASK_DOC_PREP
        and task.id == loan.current_task_id
        and task.is_latest
        and task.is_valid
    ):
        print_json("target_not_current_doc_prep", {
            "loan_current_task_id": loan.current_task_id,
            "target_task": task_brief(task),
            "mutation_included": False,
        })
        raise SystemExit(2)

    print_json("doc_prep_closing_date_state", {
        "schema": tenant["schema_name"],
        **loan_state(loan, task, proposed_date),
    })
    print_json("doc_prep_closing_date_dry_run_repair_plan", build_plan(loan, task, proposed_date))
'''
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_NUMBER__", str(int(args.application_number)))
        .replace("__TASK_ID__", str(int(args.task_id)))
        .replace("__BUSINESS_NAME__", dump_python(args.business_name))
        .replace("__PROPOSED_CLOSING_DATE__", dump_python(args.proposed_closing_date))
    )
    return textwrap.dedent(body).strip()


def sba_number_disambiguation_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    template = r'''
from django.db.models import Q

TENANT_QUERY = __TENANT_QUERY__
APPLICATION_NUMBER = __APPLICATION_NUMBER__
SBA_NUMBER = __SBA_NUMBER__
BUSINESS_NAME = __BUSINESS_NAME__


def trim(value, limit=180):
    if value in (None, ""):
        return value
    text = str(value).replace("\\n", " ")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def task_map_row(task_map):
    if not task_map:
        return None
    return {
        "name": task_map.name,
        "sub_task": task_map.sub_task,
        "sub_task_type": task_map.sub_task_type,
        "task_version": task_map.task_version,
    }


def task_brief(task):
    if not task:
        return None
    return {
        "id": task.id,
        "task_map": task_map_row(task.task_map if task.task_map_id else None),
        "status": task.get_status_display(),
        "status_id": task.status,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "created": task.created,
        "modified": task.modified,
        "actions": sorted((task.actions or {}).keys()),
        "error": trim(task.error),
    }


def request_status_row(status):
    if not status:
        return None
    return {
        "code": status.code,
        "phase": status.phase,
        "status": status.status,
        "terminal_status": status.terminal_status,
    }


def approval_docs_for(loan):
    q = (
        Q(document_type__name__iexact="approval_worksheet")
        | Q(document_type__label__icontains="Approval Worksheet")
        | Q(name__icontains="approval_worksheet")
        | Q(name__icontains="Approval_Worksheet")
        | Q(description__icontains="approval_worksheet")
    )
    return list(
        loan.documents.select_related("document_type", "created_by", "document_template")
        .filter(q)
        .order_by("-created")[:5]
    )


def terminal_task_counts(loan):
    from los.backoffice.models import TaskExecution, TaskMap

    terminal = TaskExecution.terminal_statuses()
    tasks = list(
        TaskExecution.objects.select_related("task_map")
        .filter(entity=loan, is_valid=True)
        .order_by("-created")[:250]
    )
    closing_signed = [
        task
        for task in tasks
        if task.task_map
        and task.task_map.name == TaskMap.TASK_CLOSING_FULFILLMENT
        and task.task_map.sub_task == TaskMap.SUB_TASK_REVIEW
        and task.task_map.sub_task_type == TaskMap.SUB_TASK_TYPE_SIGNED_DOCUMENTS
    ]
    closing_signed_terminal = [task for task in closing_signed if task.status in terminal]
    boarding_terminal = [
        task
        for task in tasks
        if task.task_map
        and task.task_map.name in {TaskMap.TASK_BOARDING, TaskMap.TASK_BOARDING_UPDATE}
        and task.status in terminal
    ]
    return {
        "closing_signed_docs_task_count": len(closing_signed),
        "closing_signed_docs_terminal_count": len(closing_signed_terminal),
        "boarding_terminal_count": len(boarding_terminal),
        "candidate_closing_signed_terminal_task_ids": [task.id for task in closing_signed_terminal[:5]],
        "candidate_boarding_terminal_task_ids": [task.id for task in boarding_terminal[:5]],
    }


def selected_core_steps(loan):
    response = loan.core_integration_response or {}
    selected = {}
    for key in ["create_loan", "create_customer", "centerdoc_upload"]:
        value = response.get(key)
        if isinstance(value, dict):
            selected[key] = {
                "result": value.get("result"),
                "status": value.get("status"),
                "success": value.get("success"),
                "apiSuccess": value.get("apiSuccess"),
                "loan_number": value.get("loan_number"),
                "account_number": value.get("account_number"),
                "message": trim(value.get("message")),
                "error": trim(value.get("error") or value.get("error_message")),
            }
        elif value is not None:
            selected[key] = trim(value)
    return selected


def loan_direct_fields(loan):
    values = {}
    for field in ["loan_number", "sba_number", "sba_loan_app_number", "sba_loan_status"]:
        if hasattr(loan, field):
            values[field] = getattr(loan, field)
    return values


def match_reasons(loan):
    reasons = []
    if APPLICATION_NUMBER is not None and loan.application_number == APPLICATION_NUMBER:
        reasons.append("application_number")
    for field in ["loan_number", "sba_number", "sba_loan_app_number"]:
        value = getattr(loan, field, None)
        if value not in (None, "") and str(value) == str(SBA_NUMBER):
            reasons.append(field)
    return reasons


def loan_row(loan):
    docs = approval_docs_for(loan)
    counts = terminal_task_counts(loan)
    current = loan.current_task
    current_name = current.task_map.name if current and current.task_map_id else None
    row = {
        "id": str(loan.id),
        "match_reasons": match_reasons(loan),
        "application_number": loan.application_number,
        "borrower_name": loan.borrower_name,
        "product": getattr(loan.product, "name", None),
        "request_status": request_status_row(loan.request_status if loan.request_status_id else None),
        "current_task": task_brief(current),
        "direct_identifiers": loan_direct_fields(loan),
        "closing_date": getattr(loan, "closing_date", None),
        "is_closing_date_less_than_today": getattr(loan, "is_closing_date_less_than_today", None),
        "approval_doc_count": len(docs),
        "current_task_name": current_name,
        "core_integration_response": selected_core_steps(loan),
    }
    row.update(counts)
    return row


def concrete_filter_for_identifier(Loan):
    field_map = {field.name: field for field in Loan._meta.fields}
    query = Q()
    for field_name in ["loan_number", "sba_number", "sba_loan_app_number"]:
        field = field_map.get(field_name)
        if not field:
            continue
        query |= Q(**{field_name: str(SBA_NUMBER)})
        try:
            query |= Q(**{field_name: int(SBA_NUMBER)})
        except Exception:
            pass
    try:
        query |= Q(application_number=int(SBA_NUMBER))
    except Exception:
        pass
    if APPLICATION_NUMBER is not None:
        query |= Q(application_number=APPLICATION_NUMBER)
    return query


def classify(rows):
    application_rows = [row for row in rows if "application_number" in row.get("match_reasons", [])]
    sba_rows = [row for row in rows if "sba_number" in row.get("match_reasons", [])]
    loan_number_rows = [row for row in rows if "loan_number" in row.get("match_reasons", [])]
    same_ids = {row["id"] for row in application_rows}.intersection({row["id"] for row in sba_rows})

    if loan_number_rows and not same_ids:
        hint = "separate_los_loan_number_match_found"
        next_action = "Investigate the loan_number match as the possible boarded-loan worksheet target."
    elif same_ids:
        hint = "sba_number_belongs_to_same_doc_prep_application"
        next_action = "Treat the screenshot SBA Number as ETRAN/SBA identity for the same Doc Prep application, not proof of LOS boarding."
    elif sba_rows:
        hint = "sba_number_match_found_on_different_application"
        next_action = "Compare the SBA-number match against the reported borrower/application before taking repair action."
    else:
        hint = "sba_number_not_found_in_direct_loan_fields"
        next_action = "Do not assume 8091029102 is a LOS loan number; ask for another identifier or inspect UI source/details if needed."

    worksheet_candidates = [
        row["id"]
        for row in rows
        if row.get("closing_signed_docs_terminal_count") or row.get("boarding_terminal_count") or row.get("approval_doc_count")
    ]
    return {
        "hint": hint,
        "next_action": next_action,
        "application_match_count": len(application_rows),
        "sba_number_match_count": len(sba_rows),
        "loan_number_match_count": len(loan_number_rows),
        "sba_number_same_as_application": bool(same_ids),
        "worksheet_candidate_loan_ids": worksheet_candidates,
        "mutation_included": False,
    }


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)

with schema_context(tenant["schema_name"]):
    from los.requests.models import Loan

    query = concrete_filter_for_identifier(Loan)
    loans = list(
        Loan.objects.select_related("current_task__task_map", "request_status", "product")
        .filter(query)
        .order_by("-modified")[:12]
    )
    rows = [loan_row(loan) for loan in loans]
    print_json("sba_number_disambiguation_summary", {
        "schema": tenant["schema_name"],
        "input": {
            "application_number": APPLICATION_NUMBER,
            "sba_number": SBA_NUMBER,
            "business_name": BUSINESS_NAME,
        },
        "match_count": len(rows),
        "classification": classify(rows),
        "matches": rows,
    })
'''
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_NUMBER__", str(int(args.application_number)))
        .replace("__SBA_NUMBER__", dump_python(args.sba_number))
        .replace("__BUSINESS_NAME__", dump_python(args.business_name))
    )
    return textwrap.dedent(body).strip()


def etran_status_provenance_body(args: argparse.Namespace) -> str:
    aliases = load_aliases()
    health = fetch_health(args.health_url)
    template = r'''
import ast
import json

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

TENANT_QUERY = __TENANT_QUERY__
APPLICATION_NUMBER = __APPLICATION_NUMBER__
SBA_NUMBER = __SBA_NUMBER__
BUSINESS_NAME = __BUSINESS_NAME__
MAX_ROWS = __MAX_ROWS__

WATCH_FIELDS = {
    "sba_number",
    "sba_loan_app_number",
    "sba_loan_status",
    "etran_servicing_status",
    "etran_authorization_date",
    "submitted_to_sba_at",
    "current_task",
    "request_status",
    "closing_date",
}


def trim(value, limit=220):
    if value in (None, ""):
        return value
    text = str(value).replace("\\n", " ")
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def compact_actor(actor):
    if not actor:
        return None
    return {
        "id": getattr(actor, "id", None),
        "username": getattr(actor, "username", None),
        "email": getattr(actor, "email", None),
    }


def task_map_row(task_map):
    if not task_map:
        return None
    return {
        "name": task_map.name,
        "sub_task": task_map.sub_task,
        "sub_task_type": task_map.sub_task_type,
        "task_version": task_map.task_version,
    }


def selected_mapping(data):
    if not isinstance(data, dict):
        return None
    selected = {}
    for key in sorted(data.keys()):
        key_text = str(key)
        if key_text in WATCH_FIELDS or "sba" in key_text.lower() or "etran" in key_text.lower():
            selected[key_text] = trim(data.get(key))
    return selected or None


def task_brief(task):
    if not task:
        return None
    return {
        "id": task.id,
        "task_map": task_map_row(task.task_map if task.task_map_id else None),
        "status": task.get_status_display(),
        "status_id": task.status,
        "is_latest": task.is_latest,
        "is_valid": task.is_valid,
        "actor": compact_actor(task.actor),
        "created": task.created,
        "modified": task.modified,
        "action_taken_at": task.action_taken_at,
        "internal_remarks": trim(task.internal_remarks),
        "status_reason": trim(getattr(task, "status_reason", None)),
        "error": trim(task.error),
        "actions": sorted((task.actions or {}).keys()),
        "context_selected": selected_mapping(getattr(task, "context", None) or {}),
        "details_selected": selected_mapping(getattr(task, "details", None) or {}),
    }


def request_status_row(status):
    if not status:
        return None
    return {
        "code": status.code,
        "phase": status.phase,
        "status": status.status,
        "terminal_status": status.terminal_status,
    }


def loan_snapshot(loan):
    return {
        "id": str(loan.id),
        "application_number": loan.application_number,
        "borrower_name": loan.borrower_name,
        "loan_number": loan.loan_number,
        "sba_number": getattr(loan, "sba_number", None),
        "sba_loan_app_number": getattr(loan, "sba_loan_app_number", None),
        "sba_loan_status": getattr(loan, "sba_loan_status", None),
        "etran_servicing_status": getattr(loan, "etran_servicing_status", None),
        "submitted_to_sba_at": getattr(loan, "submitted_to_sba_at", None),
        "etran_authorization_date": getattr(loan, "etran_authorization_date", None),
        "closing_date": getattr(loan, "closing_date", None),
        "current_task": task_brief(loan.current_task),
        "request_status": request_status_row(loan.request_status if loan.request_status_id else None),
    }


def parse_changes(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass
    return {}


def value_mentions_needles(value):
    text = json.dumps(value, sort_keys=True, default=str).lower()
    needles = ["sba", "etran", "funded", str(SBA_NUMBER).lower()]
    return any(needle and needle in text for needle in needles)


def compact_changes(changes):
    parsed = parse_changes(changes)
    selected = {}
    for key, value in parsed.items():
        key_text = str(key)
        if key_text in WATCH_FIELDS or "sba" in key_text.lower() or "etran" in key_text.lower() or value_mentions_needles(value):
            selected[key_text] = value
    return selected


def audit_rows_for_loan(loan):
    from los.auditlog.models import LogEntry

    ct = ContentType.objects.get_for_model(loan)
    base = LogEntry.objects.select_related("actor").filter(content_type=ct).filter(
        Q(object_pk=str(loan.pk)) | Q(object_pk=str(loan.id))
    )
    candidates = []
    recent = []
    for entry in base.order_by("-timestamp")[:120]:
        selected = compact_changes(entry.changes)
        row = {
            "id": entry.id,
            "timestamp": entry.timestamp,
            "actor": compact_actor(entry.actor),
            "action": getattr(entry, "action", None),
            "changes_selected": selected,
            "object_repr": trim(getattr(entry, "object_repr", None)),
        }
        if selected:
            candidates.append(row)
        elif len(recent) < 5:
            recent.append({k: row[k] for k in ["id", "timestamp", "actor", "action", "object_repr"]})
    return {
        "candidate_count": len(candidates),
        "candidates": list(reversed(candidates[-MAX_ROWS:])),
        "recent_nonmatching_sample": recent,
    }


def relevant_tasks_for_loan(loan):
    from los.backoffice.models import TaskExecution

    names = [
        "SBA_PROCESSING",
        "SBA_PROCESSING_PREFLIGHT",
        "SBA_ORIGINATION_SCORE_CHECK",
        "ETRAN_LOAN_UPDATE",
        "PRE_CLOSING_DOCUMENT",
        "DOC_PREP",
        "CLOSING_DOCUMENTS",
        "CLOSING_FULFILLMENT",
        "BOARDING",
        "BOARDING_UPDATE",
    ]
    rows = []
    for task in (
        TaskExecution.objects.select_related("task_map", "actor")
        .filter(entity=loan, task_map__name__in=names)
        .order_by("created")[:200]
    ):
        row = task_brief(task)
        if (
            task.task_map.name in {"SBA_PROCESSING", "SBA_PROCESSING_PREFLIGHT", "SBA_ORIGINATION_SCORE_CHECK", "ETRAN_LOAN_UPDATE"}
            or task.id == loan.current_task_id
            or value_mentions_needles(row)
        ):
            rows.append(row)
    return rows[-MAX_ROWS:]


def body_field_names(model):
    candidates = []
    for field in model._meta.fields:
        name = field.name
        if name in {
            "request_body",
            "response_body",
            "request",
            "response",
            "details",
            "payload",
            "data",
            "url",
            "request_url",
            "interface_name",
            "service_name",
        }:
            candidates.append(name)
    return candidates


def compact_log_row(obj, model):
    fields = {field.name for field in model._meta.fields}
    row = {
        "model": f"{model._meta.app_label}.{model.__name__}",
        "id": getattr(obj, "id", None),
    }
    for name in [
        "created",
        "modified",
        "request_time",
        "response_time",
        "response_code",
        "loan_id",
        "task_execution_id",
        "interface_name",
        "service_name",
        "url",
        "request_url",
    ]:
        if name in fields:
            row[name] = getattr(obj, name, None)
    selected = {}
    for name in body_field_names(model):
        value = getattr(obj, name, None)
        if value_mentions_needles(value):
            selected[name] = trim(value, limit=500)
    if selected:
        row["selected_body_fields"] = selected
    return row


def interface_log_rows(loan):
    rows = []
    errors = []
    for model in apps.get_models():
        model_name = model.__name__.lower()
        app_label = model._meta.app_label.lower()
        if not (
            app_label in {"integrations", "etran_integration"}
            or "interface" in model_name
            or "etran" in model_name
        ):
            continue
        fields = {field.name for field in model._meta.fields}
        if not ({"loan_id", "task_execution"} & fields or "etran" in model_name):
            continue
        try:
            qs = model.objects.all()
            filter_q = Q()
            if "loan_id" in fields:
                filter_q |= Q(loan_id=loan.id)
            if "task_execution" in fields:
                filter_q |= Q(task_execution__entity_id=loan.id)
            if not filter_q:
                continue
            qs = qs.filter(filter_q)
            order_field = None
            for candidate in ["response_time", "request_time", "modified", "created", "id"]:
                if candidate in fields:
                    order_field = candidate
                    break
            if order_field:
                qs = qs.order_by(f"-{order_field}")
            for obj in qs[:MAX_ROWS]:
                row = compact_log_row(obj, model)
                if value_mentions_needles(row):
                    rows.append(row)
        except Exception as exc:
            errors.append({
                "model": f"{model._meta.app_label}.{model.__name__}",
                "error": f"{type(exc).__name__}: {trim(exc)}",
            })
    return {
        "count": len(rows),
        "rows": rows[:MAX_ROWS],
        "errors": errors[:5],
    }


def classify(audit_result, task_rows, interface_result):
    status_audit = [
        row
        for row in audit_result.get("candidates", [])
        if "sba_loan_status" in row.get("changes_selected", {})
        or "etran_servicing_status" in row.get("changes_selected", {})
    ]
    task_names = [
        (row.get("task_map") or {}).get("name")
        for row in task_rows
    ]
    if status_audit:
        hint = "audit_history_identified_status_write"
        next_action = "Use the earliest status audit row as the writer/time proof, then inspect adjacent task/interface rows."
    elif "SBA_PROCESSING" in task_names:
        hint = "sba_processing_task_is_likely_write_path"
        next_action = "Inspect SBA_PROCESSING task rows and selected context/details to determine whether manual ETRAN details or ETRAN submission wrote Funded."
    elif interface_result.get("rows"):
        hint = "interface_log_rows_found_but_no_audit_status_delta"
        next_action = "Use interface log timing/body snippets to correlate the ETRAN response to the loan status."
    else:
        hint = "provenance_not_found_in_compact_surfaces"
        next_action = "Rerun with a more targeted audit/interface query after confirming table availability or UI action time."
    return {
        "hint": hint,
        "next_action": next_action,
        "status_audit_count": len(status_audit),
        "task_row_count": len(task_rows),
        "interface_log_count": interface_result.get("count"),
        "mutation_included": False,
    }


print_json("prod_health", thin_health())
tenant = resolve_tenant(TENANT_QUERY)

with schema_context(tenant["schema_name"]):
    from los.requests.models import Loan

    loan = Loan.objects.select_related("current_task__task_map", "current_task__actor", "request_status").get(
        application_number=APPLICATION_NUMBER
    )
    audit_result = audit_rows_for_loan(loan)
    task_rows = relevant_tasks_for_loan(loan)
    interface_result = interface_log_rows(loan)
    print_json("etran_status_provenance_summary", {
        "schema": tenant["schema_name"],
        "input": {
            "application_number": APPLICATION_NUMBER,
            "sba_number": SBA_NUMBER,
            "business_name": BUSINESS_NAME,
        },
        "loan": loan_snapshot(loan),
        "classification": classify(audit_result, task_rows, interface_result),
        "loan_audit": audit_result,
        "relevant_task_rows": task_rows,
        "interface_logs": interface_result,
    })
'''
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__APPLICATION_NUMBER__", str(int(args.application_number)))
        .replace("__SBA_NUMBER__", dump_python(args.sba_number))
        .replace("__BUSINESS_NAME__", dump_python(args.business_name))
        .replace("__MAX_ROWS__", str(int(args.max_rows)))
    )
    return textwrap.dedent(body).strip()


def test_loan_factory_body(args: argparse.Namespace) -> str:
    """Generate a guarded lower-environment direct test-loan creation script."""

    aliases = load_aliases()
    health = fetch_health(args.health_url)
    required_confirmation = f"CREATE_{args.environment_label}_{args.tenant}_TEST_LOAN"
    required_confirmation = "".join(
        character if character.isalnum() else "_" for character in required_confirmation.upper()
    )
    required_confirmation = "_".join(part for part in required_confirmation.split("_") if part)
    template = r'''
import hashlib
from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.db import transaction

ENVIRONMENT_LABEL = __ENVIRONMENT_LABEL__
TENANT_QUERY = __TENANT_QUERY__
TARGET_TASK = __TARGET_TASK__
SOURCE_APPLICATION = __SOURCE_APPLICATION__
IDEMPOTENCY_KEY = __IDEMPOTENCY_KEY__
MAX_CANDIDATES = __MAX_CANDIDATES__
ENABLE_CREATE = __ENABLE_CREATE__
CONFIRMATION = __CONFIRMATION__
REQUIRED_CONFIRMATION = __REQUIRED_CONFIRMATION__


def compact_task(loan):
    task = getattr(loan, "current_task", None)
    task_map = getattr(task, "task_map", None)
    return {
        "name": getattr(task_map, "name", None),
        "sub_task": getattr(task_map, "sub_task", None),
        "sub_task_type": getattr(task_map, "sub_task_type", None),
        "level": getattr(task, "level", None),
        "status": getattr(task, "status", None),
        "task_id": getattr(task, "pk", None),
    }


def compact_loan(loan):
    return {
        "loan_id": getattr(loan, "pk", None),
        "application_number": getattr(loan, "application_number", None),
        "product_id": getattr(loan, "product_id", None),
        "request_status": getattr(getattr(loan, "request_status", None), "code", None),
        "origination_source": getattr(loan, "origination_source", None),
        "created": getattr(loan, "created", None),
        "current_task": compact_task(loan),
    }


def normalized_task(value):
    return str(value or "").strip().replace("-", "_").replace(" ", "_").upper()


def require_safe_environment():
    normalized = normalized_task(ENVIRONMENT_LABEL)
    if normalized in {"PROD", "PRODUCTION"}:
        print_json(
            "test_loan_factory blocked",
            {
                "environment": ENVIRONMENT_LABEL,
                "reason": "production_is_not_supported",
                "mutation_executed": False,
            },
        )
        raise SystemExit(3)


def select_configuration_reference():
    from los.requests.models import Loan

    queryset = Loan.objects.select_related(
        "current_task__task_map",
        "product",
        "request_status",
    ).filter(current_task__isnull=False)

    if SOURCE_APPLICATION:
        queryset = queryset.filter(application_number=str(SOURCE_APPLICATION))
    if TARGET_TASK:
        queryset = queryset.filter(current_task__task_map__name__iexact=normalized_task(TARGET_TASK))

    candidates = list(queryset.order_by("-created", "-pk")[:MAX_CANDIDATES])
    print_json("test_loan_factory candidates", [compact_loan(candidate) for candidate in candidates])

    if not candidates:
        print_json(
            "test_loan_factory no_configuration_reference",
            {
                "reference_application": SOURCE_APPLICATION,
                "target_task": normalized_task(TARGET_TASK),
                "mutation_executed": False,
            },
        )
        raise SystemExit(4)

    if not SOURCE_APPLICATION and len(candidates) > 1:
        print_json(
            "test_loan_factory configuration_reference_selection_required",
            {
                "reason": "multiple_candidates",
                "next": "rerun with --source-application from the candidate list; it is used only for product/task configuration",
                "mutation_executed": False,
            },
        )
        raise SystemExit(5)

    return candidates[0]


def find_existing():
    from los.requests.models import Loan

    return (
        Loan.objects.select_related("current_task__task_map", "request_status")
        .filter(details__test_loan_factory__idempotency_key=IDEMPOTENCY_KEY)
        .order_by("-created", "-pk")
        .first()
    )


print_json("runtime_health", thin_health())
require_safe_environment()
if not IDEMPOTENCY_KEY:
    raise SystemExit("idempotency_key_required")
if not SOURCE_APPLICATION and not TARGET_TASK:
    raise SystemExit("source_application_or_target_task_required")

tenant = resolve_tenant(TENANT_QUERY)
schema_name = tenant["schema_name"]

with schema_context(schema_name):
    existing = find_existing()
    if existing:
        metadata = (existing.details or {}).get("test_loan_factory", {})
        requested_task = normalized_task(TARGET_TASK)
        conflicts = {}
        if metadata.get("environment") != ENVIRONMENT_LABEL:
            conflicts["environment"] = {
                "requested": ENVIRONMENT_LABEL,
                "existing": metadata.get("environment"),
            }
        if metadata.get("tenant_schema") != schema_name:
            conflicts["tenant_schema"] = {
                "requested": schema_name,
                "existing": metadata.get("tenant_schema"),
            }
        if SOURCE_APPLICATION and str(metadata.get("configuration_reference_application")) != str(SOURCE_APPLICATION):
            conflicts["configuration_reference_application"] = {
                "requested": str(SOURCE_APPLICATION),
                "existing": metadata.get("configuration_reference_application"),
            }
        if requested_task and normalized_task(metadata.get("requested_task")) != requested_task:
            conflicts["requested_task"] = {
                "requested": requested_task,
                "existing": metadata.get("requested_task"),
            }
        existing_task = normalized_task(compact_task(existing).get("name"))
        if requested_task and existing_task != requested_task:
            conflicts["current_task"] = {
                "requested": requested_task,
                "existing": existing_task,
            }
        if conflicts:
            print_json(
                "test_loan_factory idempotency_conflict",
                {
                    "idempotency_key": IDEMPOTENCY_KEY,
                    "conflicts": conflicts,
                    "loan": compact_loan(existing),
                    "mutation_executed": False,
                },
            )
            raise SystemExit(8)
        print_json(
            "test_loan_factory idempotent_existing",
            {
                "environment": ENVIRONMENT_LABEL,
                "tenant_schema": schema_name,
                "idempotency_key": IDEMPOTENCY_KEY,
                "loan": compact_loan(existing),
                "mutation_executed": False,
            },
        )
        raise SystemExit(0)

    reference = select_configuration_reference()
    reference_task = normalized_task(compact_task(reference).get("name"))
    requested_task = normalized_task(TARGET_TASK)
    if requested_task and reference_task != requested_task:
        print_json(
            "test_loan_factory task_mismatch",
            {
                "requested_task": requested_task,
                "reference_task": reference_task,
                "configuration_reference": compact_loan(reference),
                "mutation_executed": False,
            },
        )
        raise SystemExit(6)

    plan = {
        "environment": ENVIRONMENT_LABEL,
        "tenant_schema": schema_name,
        "idempotency_key": IDEMPOTENCY_KEY,
        "configuration_reference": compact_loan(reference),
        "requested_task": requested_task or reference_task,
        "operation": (
            "direct create: Loan + synthetic borrower/representative + TaskExecution + "
            "LoanTaskAggregator; no Loan.make_clone and no source relation reuse"
        ),
        "required_confirmation": REQUIRED_CONFIRMATION,
        "create_enabled": ENABLE_CREATE,
        "mutation_executed": False,
    }
    print_json("test_loan_factory plan", plan)

    if not ENABLE_CREATE:
        print("dry_run_only=true")
        raise SystemExit(0)
    if CONFIRMATION != REQUIRED_CONFIRMATION:
        print_json(
            "test_loan_factory confirmation_failed",
            {
                "required_confirmation": REQUIRED_CONFIRMATION,
                "mutation_executed": False,
            },
        )
        raise SystemExit(7)

    from los.backoffice.models import TaskExecution
    from los.requests.models import Loan, LoanRelation, LoanTaskAggregator, Relation
    from los.utils.bypass_automations import BypassAutomations

    digest = hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()
    entity_tin = f"66666{int(digest[:8], 16) % 10000:04d}"
    representative_tin = f"66666{int(digest[8:16], 16) % 10000:04d}"
    task_template = reference.current_task
    source_aggregator = reference.task_aggregators.filter(task_id=reference.current_task_id).first()

    with transaction.atomic(using="default"), BypassAutomations():
        metadata = {
            "idempotency_key": IDEMPOTENCY_KEY,
            "environment": ENVIRONMENT_LABEL,
            "tenant_schema": schema_name,
            "configuration_reference_application": str(reference.application_number),
            "requested_task": requested_task or reference_task,
            "creation_mode": "direct_synthetic",
        }

        new_loan = Loan(
            product=reference.product,
            request_status=reference.request_status,
            loan_amount=Decimal("100000.00"),
            term_in_months=reference.term_in_months or 60,
            rate_type=reference.rate_type or "Fixed",
            rate=reference.rate or Decimal("8.00"),
            loan_purpose=reference.loan_purpose,
            borrower_name=f"QA Test Loan {digest[:8]}",
            call_code="",
            group_code="",
            group_code_description="",
            major_code="",
            loan_delivery_method="",
            application_type="",
            details={"test_loan_factory": metadata},
        )
        new_loan.save()

        borrower = Relation.objects.create(
            party_type=Relation.ENTITY,
            entity_type="llc",
            business_name=f"QA Test Loan {digest[:8]} LLC",
            tin=entity_tin,
            tin_type="ein",
            email=f"test-loan-{digest[:12]}@example.com",
            work_phone="202-555-0100",
            business_established_date=date(2015, 1, 1),
            state_of_establishment="DE",
        )
        borrower_link = LoanRelation.objects.create(
            loan=new_loan,
            relation=borrower,
            relation_type=Relation.BORROWER,
            is_primary_borrower=True,
            is_signer=False,
            depth_level=1,
        )

        representative = Relation.objects.create(
            party_type=Relation.INDIVIDUAL,
            first_name="QA",
            last_name=f"Tester {digest[:6]}",
            tin=representative_tin,
            tin_type="ssn",
            email=f"test-loan-rep-{digest[:12]}@example.com",
            work_phone="202-555-0101",
            dob=date(1985, 1, 1),
        )
        LoanRelation.objects.create(
            loan=new_loan,
            relation=representative,
            relation_type=Relation.REPRESENTATIVE,
            parent=borrower_link,
            is_signer=True,
            position="Owner",
            depth_level=2,
        )

        task = TaskExecution.objects.create(
            slug=str(uuid4()),
            entity=new_loan,
            task_map=task_template.task_map,
            task_type=task_template.task_type,
            status=TaskExecution.IN_PROGRESS,
            is_latest=True,
            is_valid=True,
            is_manual=task_template.is_manual,
            level=task_template.level,
            actions=task_template.actions,
            allowed_operations=task_template.allowed_operations,
            internal_task_details={"test_loan_factory": metadata},
        )
        aggregator, _ = LoanTaskAggregator.update_or_create_aggregator(task)
        if source_aggregator:
            aggregator.stage = source_aggregator.stage
            aggregator.display_order = source_aggregator.display_order
            aggregator.save(update_fields=["stage", "display_order"])

        new_loan.current_task = task
        new_loan.request_status = reference.request_status
        new_loan.save(update_fields=["current_task", "request_status"])

    new_loan.refresh_from_db()
    created_task = normalized_task(compact_task(new_loan).get("name"))
    if requested_task and created_task != requested_task:
        raise RuntimeError(
            f"created loan task mismatch: expected={requested_task} actual={created_task}"
        )

    print_json(
        "test_loan_factory created",
        {
            "environment": ENVIRONMENT_LABEL,
            "tenant_schema": schema_name,
            "idempotency_key": IDEMPOTENCY_KEY,
            "configuration_reference_application": str(reference.application_number),
            "loan": compact_loan(new_loan),
            "mutation_executed": True,
        },
    )
'''
    body = (
        shared_tenant_helpers(aliases, health)
        + template.replace("__ENVIRONMENT_LABEL__", dump_python(args.environment_label))
        .replace("__TENANT_QUERY__", dump_python(args.tenant))
        .replace("__TARGET_TASK__", dump_python(args.target_task or ""))
        .replace("__SOURCE_APPLICATION__", dump_python(args.source_application or ""))
        .replace("__IDEMPOTENCY_KEY__", dump_python(args.idempotency_key))
        .replace("__MAX_CANDIDATES__", str(int(args.max_candidates)))
        .replace("__ENABLE_CREATE__", str(bool(args.enable_create)))
        .replace("__CONFIRMATION__", dump_python(args.confirmation or ""))
        .replace("__REQUIRED_CONFIRMATION__", dump_python(required_confirmation))
    )
    return textwrap.dedent(body).strip()


def queue_purge_body(args: argparse.Namespace) -> str:
    health = fetch_health(args.health_url)
    required_confirmation = f"PURGE_{args.environment_label.upper()}_CELERY_QUEUE"
    template = """
import json
import os
import time
from urllib.parse import urlparse

from django.conf import settings

PROD_HEALTH = __PROD_HEALTH__
ENVIRONMENT_LABEL = __ENVIRONMENT_LABEL__
TARGET_QUEUE = __TARGET_QUEUE__
PURGE_ENABLED = __PURGE_ENABLED__
CONFIRMATION = __CONFIRMATION__
REQUIRED_CONFIRMATION = __REQUIRED_CONFIRMATION__
MAX_DELETE_BATCHES = __MAX_DELETE_BATCHES__


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def safe_error(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:300]}


def thin_health():
    return {
        "env": PROD_HEALTH.get("Environment"),
        "build": PROD_HEALTH.get("Build Number"),
        "branch": PROD_HEALTH.get("Branch Name"),
        "commit": PROD_HEALTH.get("Commit ID"),
        "status": PROD_HEALTH.get("Status"),
    }


def broker_scheme():
    broker_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    return urlparse(broker_url).scheme.split("+")[0]


def append_unique(values, value):
    if value and value not in values:
        values.append(value)


def configured_queue_names():
    names = []
    append_unique(names, getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None))
    append_unique(names, getattr(settings, "AUDIT_LOG_QUEUE", None))
    append_unique(names, getattr(settings, "INTEGRATION_LOG_QUEUE", None))
    for route in (getattr(settings, "CELERY_TASK_ROUTES", {}) or {}).values():
        if isinstance(route, dict):
            append_unique(names, route.get("queue"))
    try:
        from los.health.checks.base import HealthCheckBase

        append_unique(names, getattr(HealthCheckBase, "celery_queue_name", None))
    except Exception:
        pass
    return names


def require_target_queue():
    if not TARGET_QUEUE or TARGET_QUEUE == "REPLACE_WITH_EXACT_QUEUE_NAME":
        print_compact(
            "queue_purge missing_target_queue",
            {
                "message": "Set TARGET_QUEUE to exactly one queue name before running a purge.",
                "configured_queues": configured_queue_names(),
                "purge_enabled": PURGE_ENABLED,
            },
        )
        raise SystemExit(2)


def require_confirmation():
    if not PURGE_ENABLED:
        return False
    if CONFIRMATION != REQUIRED_CONFIRMATION:
        print_compact(
            "queue_purge confirmation_failed",
            {
                "target_queue": TARGET_QUEUE,
                "required_confirmation": REQUIRED_CONFIRMATION,
                "purge_enabled": PURGE_ENABLED,
                "mutation_executed": False,
            },
        )
        raise SystemExit(3)
    return True


def sqs_client():
    import boto3
    from botocore.config import Config

    client_kwargs = {
        "config": Config(
            retries={
                "max_attempts": getattr(settings, "DJ_CELERY_PANEL_SQS_MAX_ATTEMPTS", 3),
                "mode": "standard",
            },
            connect_timeout=getattr(settings, "DJ_CELERY_PANEL_SQS_CONNECT_TIMEOUT", 2.0),
            read_timeout=getattr(settings, "DJ_CELERY_PANEL_SQS_READ_TIMEOUT", 5.0),
        )
    }
    region = getattr(settings, "CELERY_BROKER_AWS_REGION", "us-east-2")
    if region:
        client_kwargs["region_name"] = region
    endpoint_url = (
        (getattr(settings, "CELERY_BROKER_SQS_ENDPOINT_URL", None) or "").strip()
        or (os.environ.get("AWS_ENDPOINT_URL") or "").strip()
        or None
    )
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    access_key = getattr(settings, "CELERY_BROKER_AWS_ACCESS_KEY_ID", None)
    secret_key = getattr(settings, "CELERY_BROKER_AWS_SECRET_ACCESS_KEY", None)
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key
        session_token = getattr(settings, "CELERY_BROKER_AWS_SESSION_TOKEN", None)
        if session_token:
            client_kwargs["aws_session_token"] = session_token
    return boto3.client("sqs", **client_kwargs)


def sqs_counts(client, queue_url):
    attrs = client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    ).get("Attributes", {})
    return {
        "visible": int(attrs.get("ApproximateNumberOfMessages") or 0),
        "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible") or 0),
        "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed") or 0),
    }


def resolve_sqs_queue_url(client):
    prefix = getattr(settings, "CELERY_BROKER_SQS_QUEUE_NAME_PREFIX", "los-celery-")
    explicit_urls = tuple(getattr(settings, "DJ_CELERY_PANEL_SQS_QUEUE_URLS", ()) or ())
    if isinstance(explicit_urls, str):
        explicit_urls = (explicit_urls,) if explicit_urls.strip() else ()
    candidates = [TARGET_QUEUE]
    if prefix and not TARGET_QUEUE.startswith(prefix):
        candidates.append(prefix + TARGET_QUEUE)

    for url in explicit_urls:
        queue_name = url.rstrip("/").split("/")[-1]
        if queue_name in candidates:
            return url, queue_name

    errors = []
    for queue_name in candidates:
        try:
            return client.get_queue_url(QueueName=queue_name)["QueueUrl"], queue_name
        except Exception as exc:
            errors.append({"queue_name": queue_name, "error": safe_error(exc)})
    print_compact(
        "queue_purge sqs_resolve_failed",
        {"target_queue": TARGET_QUEUE, "candidate_names": candidates, "errors": errors},
    )
    raise SystemExit(4)


def purge_sqs_queue():
    client = sqs_client()
    queue_url, queue_name = resolve_sqs_queue_url(client)
    before = sqs_counts(client, queue_url)
    should_purge = require_confirmation()
    result = {
        "environment_label": ENVIRONMENT_LABEL,
        "broker_scheme": "sqs",
        "target_queue": TARGET_QUEUE,
        "resolved_queue_name": queue_name,
        "before": before,
        "purge_enabled": PURGE_ENABLED,
        "mutation_executed": False,
        "terminator_task_queue_db_rows_touched": False,
        "note": "SQS purge deletes available messages and may take up to 60 seconds to reflect. In-flight messages can remain until visibility timeout.",
    }
    if should_purge:
        client.purge_queue(QueueUrl=queue_url)
        result["mutation_executed"] = True
        time.sleep(3)
        result["after"] = sqs_counts(client, queue_url)
    print_compact("queue_purge sqs_result", result)


def purge_redis_queue():
    import redis

    broker_url = getattr(settings, "CELERY_BROKER_URL", "") or getattr(settings, "REDIS_URL", "")
    client = redis.Redis.from_url(broker_url)
    before_ready = int(client.llen(TARGET_QUEUE) or 0)
    should_purge = require_confirmation()
    deleted_keys = 0
    after_ready = before_ready
    if should_purge:
        deleted_keys = int(client.delete(TARGET_QUEUE) or 0)
        after_ready = int(client.llen(TARGET_QUEUE) or 0)
    print_compact(
        "queue_purge redis_result",
        {
            "environment_label": ENVIRONMENT_LABEL,
            "broker_scheme": broker_scheme(),
            "target_queue": TARGET_QUEUE,
            "before": {"ready": before_ready},
            "after": {"ready": after_ready},
            "deleted_keys": deleted_keys,
            "purge_enabled": PURGE_ENABLED,
            "mutation_executed": bool(should_purge),
            "terminator_task_queue_db_rows_touched": False,
            "note": "This deletes the ready-list key only. It does not touch Celery unacked keys or TerminatorTaskQueue DB rows.",
        },
    )


print_compact(
    "queue_purge runtime",
    {
        "environment_label": ENVIRONMENT_LABEL,
        "prod_health_argument": thin_health(),
        "broker_scheme": broker_scheme(),
        "target_queue": TARGET_QUEUE,
        "configured_queues": configured_queue_names(),
        "purge_enabled": PURGE_ENABLED,
        "required_confirmation": REQUIRED_CONFIRMATION,
        "terminator_task_queue_db_rows_touched": False,
    },
)
require_target_queue()
scheme = broker_scheme()
try:
    if scheme == "sqs":
        purge_sqs_queue()
    elif scheme in ("redis", "rediss", "valkey", "valkeys"):
        purge_redis_queue()
    else:
        print_compact(
            "queue_purge unsupported_broker",
            {
                "broker_scheme": scheme,
                "target_queue": TARGET_QUEUE,
                "mutation_executed": False,
            },
        )
        raise SystemExit(5)
except Exception as exc:
    print_compact(
        "queue_purge error",
        {
            "target_queue": TARGET_QUEUE,
            "broker_scheme": scheme,
            "error": safe_error(exc),
            "mutation_executed": False,
        },
    )
    raise
"""
    body = (
        template.replace("__PROD_HEALTH__", dump_python(health))
        .replace("__ENVIRONMENT_LABEL__", dump_python(args.environment_label))
        .replace("__TARGET_QUEUE__", dump_python(args.queue))
        .replace("__PURGE_ENABLED__", str(bool(args.enable_purge)))
        .replace("__CONFIRMATION__", dump_python(args.confirmation or ""))
        .replace("__REQUIRED_CONFIRMATION__", dump_python(required_confirmation))
        .replace("__MAX_DELETE_BATCHES__", str(int(args.max_delete_batches)))
    )
    return textwrap.dedent(body).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="task", required=True)

    tenant_map = subparsers.add_parser("tenant-map", help="Generate a prod tenant map script.")
    tenant_map.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    tenant_map.add_argument("--query", action="append", help="Tenant name/schema/domain to match. Repeat as needed.")
    tenant_map.add_argument("--full", action="store_true", help="Print a compact tenant list. Default prints matches only.")
    tenant_map.add_argument("--limit", type=int, default=25, help="Max compact tenant rows when --full is used.")
    tenant_map.add_argument("--output")

    servicing = subparsers.add_parser(
        "servicing-funds-investigation",
        help="Generate a read-only servicing funds available investigation script.",
    )
    servicing.add_argument("--tenant", required=True)
    servicing.add_argument("--loan-number")
    servicing.add_argument("--application-number", type=int)
    servicing.add_argument("--business-name")
    servicing.add_argument("--expected-ui-funds-available")
    servicing.add_argument("--expected-ui-principal-balance")
    servicing.add_argument("--around-date", help="YYYY-MM-DD date to center PaymentHistory output around.")
    servicing.add_argument("--window-days", type=int, default=45)
    servicing.add_argument("--max-payment-rows", type=int, default=8)
    servicing.add_argument("--verbose", action="store_true", help="Include extra PaymentHistory identifiers and details keys.")
    servicing.add_argument("--include-ventures-live", action="store_true")
    servicing.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    servicing.add_argument("--output")

    decline = subparsers.add_parser(
        "decline-process-investigation",
        help="Generate a read-only decline process/banner investigation script.",
    )
    decline.add_argument("--tenant", required=True)
    decline.add_argument(
        "--application",
        action="append",
        required=True,
        help="Application number, optionally NUMBER:label. Repeat for comparison cases.",
    )
    decline.add_argument("--max-task-rows", type=int, default=6)
    decline.add_argument("--max-aggregator-rows", type=int, default=10)
    decline.add_argument("--max-audit-rows", type=int, default=5)
    decline.add_argument(
        "--include-details",
        action="store_true",
        help="Print capped task, aggregator, and audit sections. Default prints one compact summary per application.",
    )
    decline.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    decline.add_argument("--output")

    repair_plan = subparsers.add_parser(
        "decline-process-repair-plan",
        help="Generate a read-only dry-run plan for decline-process terminalization repair.",
    )
    repair_plan.add_argument("--tenant", required=True)
    repair_plan.add_argument(
        "--application",
        action="append",
        required=True,
        help="Application number, optionally NUMBER:label. Repeat for exact targets.",
    )
    repair_plan.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    repair_plan.add_argument("--output")

    root_cause = subparsers.add_parser(
        "decline-process-root-cause-validation",
        help="Generate a read-only script that validates the post-decline next-step rule response and guard decision.",
    )
    root_cause.add_argument("--tenant", required=True)
    root_cause.add_argument(
        "--application",
        action="append",
        required=True,
        help="Application number, optionally NUMBER:label. Repeat for exact targets.",
    )
    root_cause.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    root_cause.add_argument("--output")

    queue_depth = subparsers.add_parser(
        "queue-depth-check",
        help="Generate a read-only script that checks Celery broker depth and TerminatorTaskQueue backlog.",
    )
    queue_depth.add_argument("--queue", action="append", help="Optional Celery/SQS queue name filter. Repeat as needed.")
    queue_depth.add_argument(
        "--terminator-status",
        action="append",
        default=["pending", "queued"],
        help="TerminatorTaskQueue status to treat as open/backlogged. Repeat as needed.",
    )
    queue_depth.add_argument("--full-threshold", type=int, default=1000)
    queue_depth.add_argument("--max-queues", type=int, default=25)
    queue_depth.add_argument("--max-rows", type=int, default=8)
    queue_depth.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    queue_depth.add_argument("--output")

    terminator_schema = subparsers.add_parser(
        "terminator-schema-check",
        help="Generate a read-only script that checks terminator settings table and migration state by tenant.",
    )
    terminator_schema.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    terminator_schema.add_argument(
        "--sweep-production",
        action="store_true",
        help="Also inspect production-ready tenants after the target tenant check.",
    )
    terminator_schema.add_argument("--max-tenants", type=int, default=150)
    terminator_schema.add_argument("--max-rows", type=int, default=8)
    terminator_schema.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    terminator_schema.add_argument("--output")

    approval_worksheet = subparsers.add_parser(
        "approval-worksheet-investigation",
        help="Generate a read-only script for Approval Worksheet / boarded-loan state mismatches.",
    )
    approval_worksheet.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    approval_worksheet.add_argument("--application-number", required=True, type=int)
    approval_worksheet.add_argument("--loan-number")
    approval_worksheet.add_argument("--business-name")
    approval_worksheet.add_argument("--max-task-rows", type=int, default=40)
    approval_worksheet.add_argument("--max-aggregator-rows", type=int, default=12)
    approval_worksheet.add_argument(
        "--include-details",
        action="store_true",
        help="Print capped task, document, and aggregator details. Default prints decision summary only.",
    )
    approval_worksheet.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    approval_worksheet.add_argument("--output")

    approval_repair = subparsers.add_parser(
        "approval-worksheet-repair-plan",
        help="Generate a read-only dry-run repair plan for Approval Worksheet / boarded-loan mismatches.",
    )
    approval_repair.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    approval_repair.add_argument("--application-number", required=True, type=int)
    approval_repair.add_argument("--loan-number")
    approval_repair.add_argument("--business-name")
    approval_repair.add_argument("--max-task-rows", type=int, default=40)
    approval_repair.add_argument("--max-aggregator-rows", type=int, default=12)
    approval_repair.add_argument(
        "--include-details",
        action="store_true",
        help="Print capped task, document, and aggregator details. Default prints decision summary only.",
    )
    approval_repair.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    approval_repair.add_argument("--output")

    doc_prep_progression = subparsers.add_parser(
        "doc-prep-progression-investigation",
        help="Generate a read-only script for stuck Doc Prep progression and validation blockers.",
    )
    doc_prep_progression.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    doc_prep_progression.add_argument("--application-number", required=True, type=int)
    doc_prep_progression.add_argument("--task-id", required=True, type=int)
    doc_prep_progression.add_argument("--business-name")
    doc_prep_progression.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    doc_prep_progression.add_argument("--output")

    doc_prep_closing_date = subparsers.add_parser(
        "doc-prep-closing-date-repair-plan",
        help="Generate a read-only dry-run plan for stale Doc Prep closing-date blockers.",
    )
    doc_prep_closing_date.add_argument(
        "--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect."
    )
    doc_prep_closing_date.add_argument("--application-number", required=True, type=int)
    doc_prep_closing_date.add_argument("--task-id", required=True, type=int)
    doc_prep_closing_date.add_argument("--business-name")
    doc_prep_closing_date.add_argument(
        "--proposed-closing-date",
        help="Optional YYYY-MM-DD business-approved date to validate and project. No mutation is generated.",
    )
    doc_prep_closing_date.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    doc_prep_closing_date.add_argument("--output")

    sba_disambiguation = subparsers.add_parser(
        "sba-number-disambiguation",
        help="Generate a read-only script that distinguishes SBA/ETRAN number from LOS loan number/application.",
    )
    sba_disambiguation.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    sba_disambiguation.add_argument("--application-number", required=True, type=int)
    sba_disambiguation.add_argument("--sba-number", required=True, help="SBA/ETRAN number shown in LOS UI.")
    sba_disambiguation.add_argument("--business-name")
    sba_disambiguation.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    sba_disambiguation.add_argument("--output")

    etran_provenance = subparsers.add_parser(
        "etran-status-provenance",
        help="Generate a read-only script that traces how SBA/ETRAN funded status was written.",
    )
    etran_provenance.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve and inspect.")
    etran_provenance.add_argument("--application-number", required=True, type=int)
    etran_provenance.add_argument("--sba-number", required=True, help="SBA/ETRAN number shown in LOS UI.")
    etran_provenance.add_argument("--business-name")
    etran_provenance.add_argument("--max-rows", type=int, default=12)
    etran_provenance.add_argument("--health-url", default=HEALTH_URL_DEFAULT)
    etran_provenance.add_argument("--output")

    test_loan_factory = subparsers.add_parser(
        "test-loan-factory",
        help="Generate a guarded lower-environment script that clones a source loan at a requested workflow task.",
    )
    test_loan_factory.add_argument("--environment-label", required=True)
    test_loan_factory.add_argument("--tenant", required=True, help="Tenant name/schema/domain to resolve.")
    test_loan_factory.add_argument(
        "--target-task",
        help="Requested current TaskMap name, such as UNDERWRITING. Required unless --source-application is used.",
    )
    test_loan_factory.add_argument(
        "--source-application",
        help="Exact source application to clone. Required when task discovery returns multiple candidates.",
    )
    test_loan_factory.add_argument("--idempotency-key", required=True)
    test_loan_factory.add_argument("--max-candidates", type=int, default=5)
    test_loan_factory.add_argument("--enable-create", action="store_true")
    test_loan_factory.add_argument(
        "--confirmation",
        help="Must match CREATE_<ENV>_<TENANT>_TEST_LOAN when --enable-create is used.",
    )
    test_loan_factory.add_argument("--health-url", default=None)
    test_loan_factory.add_argument("--output")

    queue_purge = subparsers.add_parser(
        "queue-purge",
        help="Generate a guarded script that purges one Celery broker queue after confirmation.",
    )
    queue_purge.add_argument("--queue", default="REPLACE_WITH_EXACT_QUEUE_NAME")
    queue_purge.add_argument("--environment-label", default="qa")
    queue_purge.add_argument("--enable-purge", action="store_true")
    queue_purge.add_argument("--confirmation", help="Must match PURGE_<ENV>_CELERY_QUEUE when --enable-purge is used.")
    queue_purge.add_argument("--max-delete-batches", type=int, default=500)
    queue_purge.add_argument("--health-url", default=None)
    queue_purge.add_argument("--output")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.task == "tenant-map":
        script = emit_script(tenant_map_body(args))
    elif args.task == "servicing-funds-investigation":
        script = emit_script(servicing_funds_body(args))
    elif args.task == "decline-process-investigation":
        script = emit_script(decline_process_body(args))
    elif args.task == "decline-process-repair-plan":
        script = emit_script(decline_process_repair_plan_body(args))
    elif args.task == "decline-process-root-cause-validation":
        script = emit_script(decline_process_root_cause_validation_body(args))
    elif args.task == "queue-depth-check":
        script = emit_script(queue_depth_check_body(args))
    elif args.task == "terminator-schema-check":
        script = emit_script(terminator_schema_check_body(args))
    elif args.task == "approval-worksheet-investigation":
        script = emit_script(approval_worksheet_boarding_body(args, repair_plan=False))
    elif args.task == "approval-worksheet-repair-plan":
        script = emit_script(approval_worksheet_boarding_body(args, repair_plan=True))
    elif args.task == "doc-prep-progression-investigation":
        script = emit_script(doc_prep_progression_body(args))
    elif args.task == "doc-prep-closing-date-repair-plan":
        script = emit_script(doc_prep_closing_date_repair_plan_body(args))
    elif args.task == "sba-number-disambiguation":
        script = emit_script(sba_number_disambiguation_body(args))
    elif args.task == "etran-status-provenance":
        script = emit_script(etran_status_provenance_body(args))
    elif args.task == "test-loan-factory":
        script = emit_script(test_loan_factory_body(args))
    elif args.task == "queue-purge":
        script = emit_script(queue_purge_body(args))
    else:  # pragma: no cover - argparse enforces choices
        parser.error(f"unknown task: {args.task}")

    if getattr(args, "output", None):
        Path(args.output).write_text(script, encoding="utf-8")
    else:
        sys.stdout.write(script)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
