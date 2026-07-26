PYTHONWARNINGS=ignore DD_TRACE_ENABLED=false DD_TRACE_STARTUP_LOGS=false python manage.py shell -i python

exec("""
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
""")

exec("""
import json
import os
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

PROD_HEALTH = {'Environment': 'beta', 'Build Number': 'develop.740', 'Commit ID': '5b8136b5b82db9b3dcd09fcfd276ee54ae957eff', 'Branch Name': 'develop', 'Build Start Time': '2026-06-30T19:44:12Z', 'Previous Commit ID': None, 'Status': 'Healthy'}
REQUESTED_QUEUE_FILTERS = []
TERMINATOR_OPEN_STATUSES = ['pending', 'queued']
FULL_THRESHOLD = 1000
MAX_QUEUES = 25
MAX_ROWS = 8
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
""")
