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
import time
from urllib.parse import urlparse

import boto3
from django.conf import settings

EXPECTED_HEALTH = {
    "Environment": "beta",
    "Build Number": "develop.740",
    "Commit ID": "5b8136b5b82db9b3dcd09fcfd276ee54ae957eff",
    "Branch Name": "develop",
    "Status": "Healthy",
}
TARGET_QUEUE_NAME = "los-celery-integration_log_queue"
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-2"


def print_compact(label, value):
    print(f"{label}=" + json.dumps(value, sort_keys=True, default=str))


def safe_error(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:500]}


def health_summary():
    return {
        "env": EXPECTED_HEALTH.get("Environment"),
        "build": EXPECTED_HEALTH.get("Build Number"),
        "branch": EXPECTED_HEALTH.get("Branch Name"),
        "commit": EXPECTED_HEALTH.get("Commit ID"),
        "status": EXPECTED_HEALTH.get("Status"),
    }


def broker_scheme():
    broker_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    return urlparse(broker_url).scheme.split("+")[0]


def queue_counts(sqs, queue_url):
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )["Attributes"]
    return {
        "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
        "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
    }


def main():
    print_compact("purge_queue target_health", health_summary())
    print_compact(
        "purge_queue target",
        {
            "queue": TARGET_QUEUE_NAME,
            "region": REGION,
            "broker_scheme": broker_scheme(),
            "destructive": True,
            "read_only": False,
        },
    )

    if EXPECTED_HEALTH.get("Environment") != "beta":
        raise SystemExit("Refusing purge: expected health is not beta")
    if EXPECTED_HEALTH.get("Build Number") != "develop.740":
        raise SystemExit("Refusing purge: expected build is not develop.740")
    if broker_scheme() != "sqs":
        raise SystemExit(f"Refusing purge: Celery broker scheme is {broker_scheme()!r}, not sqs")
    if TARGET_QUEUE_NAME != "los-celery-integration_log_queue":
        raise SystemExit("Refusing purge: target queue name changed")

    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.get_queue_url(QueueName=TARGET_QUEUE_NAME)["QueueUrl"]

    before = queue_counts(sqs, queue_url)
    print_compact("purge_queue before", {"queue": TARGET_QUEUE_NAME, "counts": before})

    response = sqs.purge_queue(QueueUrl=queue_url)
    status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    print_compact("purge_queue purge_response", {"queue": TARGET_QUEUE_NAME, "http_status_code": status_code})

    time.sleep(5)
    after = queue_counts(sqs, queue_url)
    print_compact(
        "purge_queue after_5s",
        {
            "queue": TARGET_QUEUE_NAME,
            "counts": after,
            "note": "SQS purge can take up to 60 seconds to fully settle.",
        },
    )


try:
    main()
except Exception as exc:
    print_compact("purge_queue error", {"error": safe_error(exc), "queue": TARGET_QUEUE_NAME})
    raise
""")
