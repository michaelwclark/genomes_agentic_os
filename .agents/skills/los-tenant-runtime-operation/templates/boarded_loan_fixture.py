# Helpers inlined into the guarded test-loan factory's boarded mode.
# Only the explicitly requested synthetic graph is written. Qualification uses
# the application's own read-only servicing and loan-modification managers.


def boarded_require(condition, reason):
    if not condition:
        print_json("test_loan_factory boarded_blocked", {
            "reason": reason, "mutation_executed": False,
        })
        raise SystemExit(9)


def boarded_loan_number():
    return LOAN_NUMBER or "QA-" + hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()[:16].upper()


def boarded_borrower_username():
    return "qa-boarded-" + hashlib.sha256(IDEMPOTENCY_KEY.encode()).hexdigest()[:20]


def boarded_notification_boundary():
    from unittest.mock import patch
    from terminator.managers import TerminatorManager

    # The standalone fixture process writes only its fresh synthetic graph.
    # Loan-created notifications and deferred trigger logging do not honor the
    # normal automation bypass. Keep this boundary through outer commit.
    return patch.object(TerminatorManager, "execute_trigger", return_value=[])


def boarded_terms(term_in_months, rate):
    from datetime import timedelta

    term = int(term_in_months or 60)
    annual_rate = Decimal(str(rate if rate is not None else "8.00"))
    boarded_require(term > 0 and annual_rate >= 0, "invalid_synthetic_repayment_terms")
    monthly_rate = annual_rate / Decimal("1200")
    principal = Decimal("100000.00")
    payment = (principal * monthly_rate / (1 - (1 + monthly_rate) ** (-term))
               if monthly_rate else principal / term).quantize(Decimal("0.01"))
    return {
        "closing_date": date.today() - timedelta(days=30),
        "maturity_date": date.today() + timedelta(days=max(365, round(term * 365.25 / 12))),
        "payment_start_date": date.today() + timedelta(days=30),
        "payment": payment,
    }


def boarded_direct_setup_checks(account, actor):
    from datetime import timedelta
    from los.servicing.api.serializers import DirectLoanModificationRequestSerializer
    from los.workflows.managers.loan_modification import LoanModificationManager

    validator = getattr(LoanModificationManager, "_validate_direct_modification_type", None)
    choices = getattr(LoanModificationManager, "_get_direct_short_term_extension_day_choices", None)
    boarded_require(callable(validator) and callable(choices), "direct_lender_setup_validator_not_available")
    source = account.loan_for_modification
    boarded_require(source is not None and source.maturity_date is not None, "source_maturity_date_required")
    days = sorted(int(value) for value in choices() if int(value) > 0)
    boarded_require(bool(days), "short_term_extension_choices_required")
    renewal_date = max(source.maturity_date, date.today()) + timedelta(days=365)
    examples = [
        {"modification_type": "short_term_extension", "extension_days": days[0]},
        {"modification_type": "renewal", "renewal_maturity_date": renewal_date.isoformat(),
         "renewal_reason": "Synthetic QA loan modification qualification"},
    ]
    for example in examples:
        serializer = DirectLoanModificationRequestSerializer(data=example)
        serializer.is_valid(raise_exception=True)
        # This validates only. Neither service-request creation nor queuing is called.
        validator(loan_validation=account, user=actor, **serializer.validated_data)
    return {
        "qualified_lender_setup_types": [item["modification_type"] for item in examples],
        "extension_days_example": days[0],
        "renewal_maturity_date_example": renewal_date.isoformat(),
    }


def boarded_runtime_gates(account):
    from constance import config
    from django.contrib.auth import get_user_model
    from django_tenants.utils import get_tenant_model
    from los.configurations.models import Configuration
    from los.search.managers.actions import LoanValidationActions
    from los.workflows.managers.loan_modification import LoanModificationManager
    from los.workflows.models import TaskWorkflow

    actor = get_user_model().objects.using("default").get(username=ACTOR_USERNAME)
    boarded_require(actor.is_active and actor.is_backoffice_user, "active_backoffice_actor_required")
    org = get_tenant_model().get_configuration(Configuration.ORGANIZATION_CONFIG).details
    groups = org.get("loan_modification_authorized_groups", [])
    boarded_require(not groups or actor.has_group(groups), "actor_not_authorized_for_loan_modification")
    boarded_require(config.ENABLE_LOAN_MODS, "loan_modifications_disabled")
    # Ventures eligibility is local field inspection. Other providers require a
    # separately qualified profile, rather than guessed status values or calls.
    provider = account.servicing_config.get("servicing_provider")
    boarded_require(provider == "ventures", "unsupported_boarded_servicing_provider")
    boarded_require(account.is_funded and account.is_active, "funded_active_account_required")
    workflows = TaskWorkflow.objects.using("default").filter(name=LoanModificationManager.WORKFLOW_NAME)
    boarded_require(workflows.count() == 1, "exact_loan_modification_workflow_required")
    guard_method = getattr(LoanModificationManager, "get_active_loan_modification_guard", None)
    boarded_require(callable(guard_method), "loan_modification_guard_not_available")
    guard = guard_method(account)
    boarded_require(guard.service_request is None and not guard.has_active_application,
                    "active_loan_modification_conflict")
    action = LoanValidationActions(actor, account).get_can_start_loan_modification()
    boarded_require(action.get("value") is True, "accounts_action_does_not_allow_loan_modification")
    modifications = LoanModificationManager.available_loan_modifications(account, user=actor)
    boarded_require(bool(modifications), "no_loan_modification_types_for_actor")
    qualification = {
        "actor_username": actor.username,
        "actor_is_backoffice": True,
        "actor_authorized": True,
        "servicing_provider": provider,
        "is_funded": True,
        "is_active": True,
        "can_start_loan_modification": True,
        "available_loan_modifications": sorted(str(item) for item in modifications),
        "loan_modification_workflow_id": str(workflows.first().pk),
        "active_modification_conflict": False,
    }
    qualification.update(boarded_direct_setup_checks(account, actor))
    return actor, qualification


def boarded_preflight(reference):
    from django.contrib.auth import get_user_model
    from los.backoffice.models import TaskExecution, TaskMap
    from los.requests.models import Loan
    from los.servicing.models import LoanValidation

    boarded_require(SOURCE_LOAN_ID and ACTOR_USERNAME, "source_loan_id_and_actor_required")
    boarded_require(normalized_task(ENVIRONMENT_LABEL) in {
        "QA", "QA_MULTI", "BETA", "BETA_MULTI", "PREPROD", "DEV", "DEVELOPMENT", "LOCAL", "TEST",
    }, "explicit_lower_environment_required")
    boarded_require(str(reference.pk) == SOURCE_LOAN_ID, "configuration_reference_loan_id_mismatch")
    names = [TaskMap.TASK_BOARDING, TaskMap.TASK_BOARDING_UPDATE]
    if TARGET_TASK:
        boarded_require(normalized_task(TARGET_TASK) in names, "boarded_task_must_be_boarding")
        names = [normalized_task(TARGET_TASK)]
    tasks = reference.taskexecution_set.using("default").filter(
        task_map__name__in=names, is_valid=True,
        status__in=[TaskExecution.ACCEPT, TaskExecution.COMPLETE],
    )
    task_template = tasks.order_by("-created", "-pk").first()
    boarded_require(task_template is not None, "completed_valid_boarding_reference_required")
    status = reference.request_status
    boarded_require(status is not None and status.terminal_status and not reference.is_loan_mod
                    and not status.code.endswith(("__WITHDRAWN", "__DECLINED", "__APPROVED_NOT_ACCEPTED")),
                    "terminal_originated_reference_required")
    boarded_require(reference.product_id is not None and reference.product is not None,
                    "reference_product_required")
    number = boarded_loan_number()
    boarded_require(len(number) <= 255 and number == number.strip() and bool(number), "invalid_loan_number")
    boarded_require(not LoanValidation.objects.using("default").filter(loan_number=number).exists()
                    and not Loan.objects.using("default").filter(loan_number=number).exists(), "synthetic_loan_number_conflict")
    boarded_require(not get_user_model().objects.using("default").filter(username=boarded_borrower_username()).exists(),
                    "synthetic_borrower_identity_conflict")
    projected = LoanValidation(
        business_name="QA Test Loan", primary_borrower_name="QA Test Loan",
        loan_number=number, loan_status="Funded", loan_sub_status="Active",
    )
    terms = boarded_terms(reference.term_in_months, reference.rate)
    projected_source = Loan(
        product=reference.product, request_status=status, loan_amount=Decimal("100000.00"),
        term_in_months=reference.term_in_months or 60, rate=reference.rate or Decimal("8.00"),
        maturity_date=terms["maturity_date"], application_type="",
    )
    projected_source.all_service_requests = []
    # Project the new account's qualifying request without saving either row.
    # Its task/status configuration comes from the exact immutable reference.
    projected.__dict__["loan_for_modification"] = projected_source
    actor, qualification = boarded_runtime_gates(projected)
    return {
        "actor": actor, "task_template": task_template,
        "qualification": qualification, "loan_number": number,
        "reference_task_id": str(task_template.pk),
        "request_status_code": status.code,
    }


def create_boarded_account(loan, borrower, representative):
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from los.crm.models.abstract import PartyType, TinType
    from los.requests.models import Loan
    from los.servicing.models import LoanValidation

    terms = boarded_terms(loan.term_in_months, loan.rate)
    primary_user = get_user_model()(
        username=boarded_borrower_username(), email=representative.email,
        first_name="QA", last_name="Boarded Borrower", is_borrower=True,
        is_active=False, is_staff=False, is_superuser=False, is_backoffice_user=False,
    )
    primary_user.set_unusable_password()
    primary_user.save()
    account = LoanValidation.objects.using("default").create(
        business_name=borrower.business_name, primary_borrower_name=borrower.business_name,
        primary_borrower_email=borrower.email, primary_phone=borrower.work_phone,
        party_type=PartyType.ENTITY, business_type=BORROWER_ENTITY_TYPE,
        tin=borrower.tin, tin_type=TinType.EIN,
        application_number=loan.application_number, loan_number=boarded_loan_number(),
        loan_status="Funded", loan_sub_status="Active",
        initial_approved_amount=loan.loan_amount, current_approval_amount=loan.loan_amount,
        outstanding_balance=loan.loan_amount, total_undisbursed_amount=Decimal("0.00"),
        initial_disbursement_date=terms["closing_date"], maturity_date=terms["maturity_date"],
        interest_rate=loan.rate, rate_type=loan.rate_type,
        original_payment_amount=terms["payment"], loan_payment_amount=terms["payment"],
        payment_due_date=terms["payment_start_date"],
    )
    loan.loan_validation = account
    loan.loan_number = account.loan_number
    boarded_at = timezone.now()
    loan.primary_user = primary_user
    loan.closing_date = terms["closing_date"]
    loan.maturity_date = terms["maturity_date"]
    loan.payment_start_date = terms["payment_start_date"]
    loan.first_payment_date = terms["payment_start_date"]
    loan.save(update_fields=["loan_validation", "loan_number", "primary_user",
                             "closing_date", "maturity_date", "payment_start_date", "first_payment_date"])
    # A model-save boarding transition enrolls some products in external bank
    # monitoring even with automation bypass. Update this new synthetic row
    # directly, after saving its other fields, so that lifecycle hook never runs.
    changed = Loan.objects.using("default").filter(pk=loan.pk).update(boarded_date=boarded_at)
    boarded_require(changed == 1, "synthetic_boarding_date_update_failed")
    loan.boarded_date = boarded_at
    loan.users.add(primary_user)
    account.users.add(primary_user)
    representative.user = primary_user
    representative.save(update_fields=["user"])
    return account


def verify_boarded_side_effects(loan, account, user):
    from django.contrib.contenttypes.models import ContentType
    from los.requests.models import LoanRelation, Relation
    from los.servicing.models import BankConnectMonitoringEnrollment
    from terminator.models import TerminatorTaskQueue

    relations = list(LoanRelation.objects.using("default").filter(loan=loan).select_related("relation"))
    boarded_require(len(relations) == 2, "synthetic_relation_graph_changed")
    borrower = next((row for row in relations if row.is_primary_borrower
                     and row.relation_type == Relation.BORROWER), None)
    representative = next((row for row in relations if row.relation_type == Relation.REPRESENTATIVE), None)
    boarded_require(borrower is not None and representative is not None
                    and borrower.relation.entity_type == BORROWER_ENTITY_TYPE
                    and representative.relation.user_id == user.pk
                    and borrower.relation.tin == account.tin,
                    "synthetic_borrower_representative_link_mismatch")
    boarded_require(not BankConnectMonitoringEnrollment.objects.using("default").filter(
        loan_validation_id=account.pk).exists(), "unexpected_bank_monitoring_enrollment")
    manager = getattr(TerminatorTaskQueue, "all_objects", TerminatorTaskQueue.objects).using("default")
    objects = [loan, account, user, loan.current_task, *[row.relation for row in relations]]
    for obj in objects:
        content_type = ContentType.objects.db_manager("default").get_for_model(obj)
        boarded_require(not manager.filter(content_type=content_type, object_pk=str(obj.pk)).exists(),
                        "unexpected_synthetic_workflow_queue_entry")
    return {"bank_monitoring_enrollment_count": 0, "workflow_queue_entry_count": 0}


def verify_boarded_fixture(loan):
    from los.backoffice.models import TaskExecution, TaskMap
    from los.servicing.models import LoanValidation

    boarded_require(loan.loan_validation_id is not None, "servicing_account_missing")
    account = LoanValidation.objects.using("default").get(pk=loan.loan_validation_id)
    boarded_require(account.loan_number == boarded_loan_number() == loan.loan_number,
                    "servicing_account_number_mismatch")
    boarded_require(account.application_number == loan.application_number and loan.boarded_date is not None,
                    "boarded_application_link_mismatch")
    boarded_require(loan.maturity_date is not None and account.maturity_date == loan.maturity_date
                    and account.loan_payment_amount is not None and account.loan_payment_amount > 0
                    and account.initial_disbursement_date is not None
                    and account.interest_rate == loan.rate and account.payment_due_date == loan.payment_start_date,
                    "synthetic_repayment_terms_missing")
    task = loan.current_task
    boarded_require(task is not None and task.task_map is not None and task.is_valid and task.is_latest
                    and task.status == TaskExecution.COMPLETE
                    and task.task_map.name in [TaskMap.TASK_BOARDING, TaskMap.TASK_BOARDING_UPDATE],
                    "completed_valid_boarding_proof_missing")
    metadata = (loan.details or {}).get("test_loan_factory", {})
    boarded_require(normalized_task(metadata.get("requested_task")) == task.task_map.name,
                    "requested_boarding_task_changed")
    boarded_require(loan.request_status.terminal_status and not loan.is_loan_mod
                    and not loan.request_status.code.endswith(("__WITHDRAWN", "__DECLINED", "__APPROVED_NOT_ACCEPTED")),
                    "terminal_originated_status_missing")
    user = loan.primary_user
    boarded_require(user is not None and user.username == boarded_borrower_username()
                    and user.is_borrower and not user.is_active and not user.has_usable_password()
                    and loan.users.filter(pk=user.pk).exists() and account.users.filter(pk=user.pk).exists(),
                    "synthetic_primary_applicant_link_missing")
    boarded_require(loan.primary_applicant.pk == user.pk, "primary_applicant_mismatch")
    boarded_require(account.loan_for_modification is not None
                    and account.loan_for_modification.pk == loan.pk, "modification_source_request_mismatch")
    actor, qualification = boarded_runtime_gates(account)
    qualification.update(verify_boarded_side_effects(loan, account, user))
    qualification.update({
        "loan_validation_id": str(account.pk), "loan_number": account.loan_number,
        "primary_applicant_id": str(user.pk), "primary_applicant_login_enabled": False,
        "boarding_task_id": str(task.pk), "request_status_code": loan.request_status.code,
    })
    return qualification
