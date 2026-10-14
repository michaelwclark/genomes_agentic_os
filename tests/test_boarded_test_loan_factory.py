"""Behavioral safety checks for generated boarded loan-modification fixtures."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import sys
import types
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/los-tenant-runtime-operation"
SPEC = importlib.util.spec_from_file_location("boarded_factory_generator", SKILL / "scripts/build_tenant_runtime_operation.py")
assert SPEC and SPEC.loader
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def generated_body(*extra: str) -> str:
    args = GENERATOR.build_parser().parse_args([
        "test-loan-factory", "--environment-label", "beta-multi", "--tenant", "fixture-bank",
        "--source-application", "12345678901", "--idempotency-key", "boarded-fixture-test", *extra,
    ])
    return GENERATOR.test_loan_factory_body(args)


def helper_namespace():
    namespace = {
        "hashlib": hashlib, "Decimal": Decimal, "date": date,
        "LOAN_NUMBER": "", "IDEMPOTENCY_KEY": "boarded-fixture-test", "ACTOR_USERNAME": "fixture-lender",
        "print_json": Mock(),
    }
    exec((SKILL / "templates/boarded_loan_fixture.py").read_text(), namespace)
    return namespace


def module_tree(entries):
    modules = {}
    for name, values in entries.items():
        parts = name.split(".")
        for size in range(1, len(parts) + 1):
            key = ".".join(parts[:size])
            if key not in modules:
                modules[key] = types.ModuleType(key)
                modules[key].__path__ = []
        modules[name].__dict__.update(values)
    return modules


class FactoryRenderingTests(unittest.TestCase):
    def test_default_path_and_borrower_entity_selection_are_preserved(self):
        body = generated_body("--borrower-entity-type", "trust")
        compile(body, "workflow_factory", "exec")
        self.assertIn("FIXTURE_STATE = 'workflow'", body)
        self.assertIn("BORROWER_ENTITY_TYPE = 'trust'", body)
        self.assertIn("TaskExecution.COMPLETE if boarded else TaskExecution.IN_PROGRESS", body)
        self.assertIn("metadata.get(\"borrower_entity_type\", \"llc\")", body)
        self.assertNotIn(".make_clone()", body)

    def test_boarded_alias_renders_executable_body_and_distinct_confirmation(self):
        body = generated_body(
            "--boarded", "--source-loan-id", "11111111-1111-1111-1111-111111111111",
            "--actor-username", "fixture-lender", "--enable-create",
            "--confirmation", "CREATE_BETA_MULTI_FIXTURE_BANK_BOARDED_TEST_LOAN",
        )
        compile(body, "boarded_factory", "exec")
        script = GENERATOR.emit_script(body)
        for call in [n for n in ast.walk(ast.parse(script.split("\n", 2)[2])) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "exec"]:
            compile(ast.literal_eval(call.args[0]), "emitted_exec", "exec")
        self.assertIn("FIXTURE_STATE = 'boarded'", body)
        self.assertIn("CREATE_BETA_MULTI_FIXTURE_BANK_BOARDED_TEST_LOAN", body)
        self.assertIn("pg_advisory_xact_lock", body)
        self.assertIn("verify_boarded_fixture(existing)", body)
        self.assertLess(body.index("boarded_notification_boundary() if FIXTURE_STATE"),
                        body.index("transaction.atomic(using=\"default\") if FIXTURE_STATE"))
        self.assertLess(body.index("qualification = verify_boarded_fixture(new_loan)"),
                        body.index("new_loan.refresh_from_db()"))

    def test_duplicate_source_applications_require_an_exact_loan_id(self):
        body = generated_body()
        self.assertIn("if len(candidates) > 1:", body)
        self.assertIn("queryset = queryset.filter(pk=SOURCE_LOAN_ID)", body)
        self.assertIn("if TARGET_TASK and FIXTURE_STATE != \"boarded\"", body)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.ns = helper_namespace()
        self.actor = types.SimpleNamespace(username="fixture-lender", is_active=True, is_backoffice_user=True,
                                          has_group=Mock(return_value=True))
        self.account = types.SimpleNamespace(
            servicing_config={"servicing_provider": "ventures"}, is_funded=True, is_active=True,
            loan_for_modification=types.SimpleNamespace(maturity_date=date.today() + timedelta(days=365)),
        )
        self.config = types.SimpleNamespace(ENABLE_LOAN_MODS=True)
        self.org_details = {"loan_modification_authorized_groups": ["Loan Modification Lender"]}
        self.guard = types.SimpleNamespace(service_request=None, has_active_application=False)
        self.manager = types.SimpleNamespace(
            WORKFLOW_NAME="LOAN_MODIFICATION", get_active_loan_modification_guard=Mock(return_value=self.guard),
            available_loan_modifications=Mock(return_value={"change_loan_terms": {}, "loan_renewal": {}}),
            _get_direct_short_term_extension_day_choices=Mock(return_value=[30, 60]),
            _validate_direct_modification_type=Mock(),
        )
        self.action = Mock(return_value={"value": True, "reason": ""})
        self.workflow = Mock()
        self.workflow.using.return_value = self.workflow
        self.workflow.filter.return_value = self.workflow
        self.workflow.count.return_value = 1
        self.workflow.first.return_value = types.SimpleNamespace(pk="workflow-id")
        users = Mock()
        users.using.return_value = users
        users.get.return_value = self.actor

        class Serializer:
            def __init__(self, data):
                self.validated_data = data

            def is_valid(self, raise_exception=False):
                return True

        entries = {
            "constance": {"config": self.config},
            "django.contrib.auth": {"get_user_model": lambda: types.SimpleNamespace(objects=users)},
            "django_tenants.utils": {"get_tenant_model": lambda: types.SimpleNamespace(
                get_configuration=lambda *a, **k: types.SimpleNamespace(details=self.org_details))},
            "los.configurations.models": {"Configuration": types.SimpleNamespace(ORGANIZATION_CONFIG="org")},
            "los.search.managers.actions": {"LoanValidationActions": lambda *a: types.SimpleNamespace(
                get_can_start_loan_modification=self.action)},
            "los.workflows.managers.loan_modification": {"LoanModificationManager": self.manager},
            "los.workflows.models": {"TaskWorkflow": types.SimpleNamespace(objects=self.workflow)},
            "los.servicing.api.serializers": {"DirectLoanModificationRequestSerializer": Serializer},
        }
        self.patch = patch.dict(sys.modules, module_tree(entries))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def assert_blocked(self, reason):
        with self.assertRaises(SystemExit) as error:
            self.ns["boarded_runtime_gates"](self.account)
        self.assertEqual(error.exception.code, 9)
        self.assertEqual(self.ns["print_json"].call_args.args[1]["reason"], reason)

    def test_qualification_uses_actor_and_both_read_only_direct_setup_validators(self):
        actor, qualification = self.ns["boarded_runtime_gates"](self.account)
        self.assertIs(actor, self.actor)
        self.assertEqual(qualification["qualified_lender_setup_types"], ["short_term_extension", "renewal"])
        self.assertEqual(self.manager._validate_direct_modification_type.call_count, 2)
        self.manager.available_loan_modifications.assert_called_once_with(self.account, user=self.actor)
        self.actor.has_group.assert_called_once_with(["Loan Modification Lender"])

    def test_backoffice_and_group_authorization_are_separate_gates(self):
        self.actor.is_backoffice_user = False
        self.assert_blocked("active_backoffice_actor_required")
        self.actor.is_backoffice_user = True
        self.actor.has_group.return_value = False
        self.assert_blocked("actor_not_authorized_for_loan_modification")
        self.manager.available_loan_modifications.assert_not_called()

    def test_unfunded_inactive_disabled_and_unqualified_provider_are_blocked(self):
        cases = [("is_funded", False), ("is_active", False)]
        for name, value in cases:
            setattr(self.account, name, value)
            self.assert_blocked("funded_active_account_required")
            setattr(self.account, name, True)
        self.config.ENABLE_LOAN_MODS = False
        self.assert_blocked("loan_modifications_disabled")
        self.config.ENABLE_LOAN_MODS = True
        self.account.servicing_config = {"servicing_provider": "unqualified"}
        self.assert_blocked("unsupported_boarded_servicing_provider")

    def test_any_active_modification_in_flight_is_blocked(self):
        self.guard.service_request = object()
        self.assert_blocked("active_loan_modification_conflict")
        self.guard.service_request = None
        self.guard.has_active_application = True
        self.assert_blocked("active_loan_modification_conflict")
        self.manager.available_loan_modifications.assert_not_called()

    def test_menu_visibility_is_not_sufficient_when_no_modifications_are_available(self):
        self.manager.available_loan_modifications.return_value = {}
        self.assert_blocked("no_loan_modification_types_for_actor")
        self.manager._validate_direct_modification_type.assert_not_called()

    def test_workflow_and_primary_maturity_are_required(self):
        self.workflow.count.return_value = 0
        self.assert_blocked("exact_loan_modification_workflow_required")
        self.workflow.count.return_value = 1
        self.account.loan_for_modification.maturity_date = None
        self.assert_blocked("source_maturity_date_required")

    def test_identifiers_are_deterministic_and_repayment_terms_are_usable(self):
        number = self.ns["boarded_loan_number"]()
        self.assertEqual(number, self.ns["boarded_loan_number"]())
        self.assertTrue(number.startswith("QA-"))
        self.ns["IDEMPOTENCY_KEY"] = "a-different-fixture"
        self.assertNotEqual(number, self.ns["boarded_loan_number"]())
        terms = self.ns["boarded_terms"](60, Decimal("8.00"))
        self.assertGreater(terms["maturity_date"], date.today())
        self.assertGreater(terms["payment"], Decimal("0"))
        self.assertEqual(self.ns["boarded_terms"](60, Decimal("0"))["payment"], Decimal("1666.67"))


class AutomationBoundaryTests(unittest.TestCase):
    def test_creation_and_commit_callbacks_cannot_dispatch_triggers(self):
        namespace = helper_namespace()
        queue = []
        dispatcher = Mock(side_effect=lambda **kwargs: queue.append(kwargs))
        manager = types.SimpleNamespace(execute_trigger=dispatcher)

        class Commit:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                manager.execute_trigger(trigger="on_commit_notification")

        with patch.dict(sys.modules, module_tree({"terminator.managers": {"TerminatorManager": manager}})):
            with namespace["boarded_notification_boundary"](), Commit():
                manager.execute_trigger(trigger="application_started_alert")
            self.assertEqual(queue, [])
            dispatcher.assert_not_called()
            self.assertIs(manager.execute_trigger, dispatcher)

    def test_boarding_date_avoids_model_hooks_and_payment_override_survives_save(self):
        namespace = helper_namespace()
        namespace["BORROWER_ENTITY_TYPE"] = "llc"
        board_updates = []
        account = types.SimpleNamespace(loan_number="QA-NUMBER", users=types.SimpleNamespace(add=Mock()))
        account_manager = Mock()
        account_manager.using.return_value = account_manager
        account_manager.create.return_value = account
        loan_manager = Mock()
        loan_manager.using.return_value = loan_manager
        loan_manager.filter.return_value = loan_manager
        loan_manager.update.side_effect = lambda **kwargs: board_updates.append(kwargs) or 1

        class SyntheticUser:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.pk = "synthetic-user"
                self.set_unusable_password = Mock()
                self.save = Mock()

        loan = types.SimpleNamespace(
            pk="synthetic-loan", term_in_months=60, rate=Decimal("8.00"), rate_type="Fixed",
            loan_amount=Decimal("100000.00"), application_number=12345678901, boarded_date=None,
            users=types.SimpleNamespace(add=Mock()), first_payment_date=None,
        )
        saved_fields = []

        def model_save(*, update_fields):
            self.assertIsNone(loan.boarded_date)
            self.assertNotIn("boarded_date", update_fields)
            saved_fields.extend(update_fields)
            # Mirror the deployed save's documented first-payment precedence.
            loan.payment_start_date = loan.first_payment_date or date.today()

        loan.save = model_save
        borrower = types.SimpleNamespace(business_name="Synthetic LLC", email="borrower@example.com",
                                         work_phone="202-555-0100", tin="666660001")
        representative = types.SimpleNamespace(email="representative@example.com", save=Mock())
        entries = {
            "django.contrib.auth": {"get_user_model": lambda: SyntheticUser},
            "django.utils": {"timezone": types.SimpleNamespace(now=lambda: "boarded-timestamp")},
            "los.crm.models.abstract": {"PartyType": types.SimpleNamespace(ENTITY="entity"),
                                         "TinType": types.SimpleNamespace(EIN="EIN")},
            "los.requests.models": {"Loan": types.SimpleNamespace(objects=loan_manager)},
            "los.servicing.models": {"LoanValidation": types.SimpleNamespace(objects=account_manager)},
        }
        with patch.dict(sys.modules, module_tree(entries)):
            namespace["create_boarded_account"](loan, borrower, representative)
        self.assertEqual(board_updates, [{"boarded_date": "boarded-timestamp"}])
        self.assertEqual(loan.boarded_date, "boarded-timestamp")
        self.assertIn("first_payment_date", saved_fields)
        self.assertEqual(loan.payment_start_date, account_manager.create.call_args.kwargs["payment_due_date"])
        loan_manager.filter.assert_called_once_with(pk="synthetic-loan")


if __name__ == "__main__":
    unittest.main()
