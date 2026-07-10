"""Offline contract tests for CC-209 Wave 1 adaptive policy resolution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.adaptive_policy import (
    DEFAULT_MODEL_CATALOG,
    FEATURE_62_STATIC_FALLBACK,
    LUNA_EFFORTS,
    SOL_EFFORTS,
    TERRA_EFFORTS,
    TIER_ROUTES,
    AdaptivePolicy,
    CapabilityTier,
    CapabilityUnavailableError,
    HumanApprovalRequiredError,
    ModelCandidate,
    ModelCapability,
    ModelCatalog,
    ModelTier,
    PolicyLayers,
    PolicyMode,
    PolicyOverrides,
    PolicyValidationError,
    ReasoningEffort,
    RoutingRequest,
    RuntimePolicyDocument,
    TierRoute,
    load_adaptive_policy_yaml,
    load_policy_file,
    load_policy_text,
    resolve_layered_policy,
    resolve_mode,
    resolve_policy,
    resolve_tier,
    validate_policy,
)
from genomes_agentic_os.config_ops import config_template
from genomes_agentic_os.task_assessment import assess_task


TEMPLATE = Path(__file__).parents[1] / "templates/runtime/adaptive-router.yml"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _template_data() -> dict[str, object]:
    loaded = yaml.safe_load(_template_text())
    assert isinstance(loaded, dict)
    return loaded


def _load_data(data: dict[str, object]) -> RuntimePolicyDocument:
    return load_policy_text(yaml.safe_dump(data, sort_keys=False))


def test_capability_records_expose_authoritative_tiers_ranks_and_efforts() -> None:
    luna = DEFAULT_MODEL_CATALOG.get("economy")
    terra = DEFAULT_MODEL_CATALOG.get("balanced")
    sol = DEFAULT_MODEL_CATALOG.get("frontier")

    assert luna is not None and terra is not None and sol is not None
    assert luna.model_id == "gpt-5.6-luna"
    assert luna.capability_tier is CapabilityTier.ECONOMY
    assert luna.capability_rank == 0
    assert terra.model_id == "gpt-5.6-terra"
    assert terra.capability_tier is CapabilityTier.BALANCED
    assert terra.capability_rank == 1
    assert sol.model_id == "gpt-5.6-sol"
    assert sol.capability_tier is CapabilityTier.FRONTIER
    assert sol.capability_rank == 2
    assert luna.coding and luna.tool_use and luna.context_tokens >= 32_000
    assert luna.subagent_suitable and luna.cost_class.value == "economy"
    assert LUNA_EFFORTS == (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
        ReasoningEffort.MAX,
    )
    assert TERRA_EFFORTS == SOL_EFFORTS == LUNA_EFFORTS + (
        ReasoningEffort.ULTRA,
    )
    with pytest.raises(Exception):
        DEFAULT_MODEL_CATALOG.records[0].available = False  # type: ignore[misc]


def test_feature_62_generated_static_config_is_unchanged_by_resolution() -> None:
    """A real config_ops rendering snapshot proves resolution is read-only."""

    before = config_template("project")

    result = resolve_policy(AdaptivePolicy(mode=PolicyMode.GUARDED))

    assert result.selection is not None
    assert config_template("project") == before
    off = resolve_policy(AdaptivePolicy())
    assert off.static_fallback == FEATURE_62_STATIC_FALLBACK
    assert config_template("project") == before

    loaded_off = resolve_policy(load_policy_file(TEMPLATE))
    assert loaded_off.static_fallback == FEATURE_62_STATIC_FALLBACK
    assert config_template("project") == before


def test_precedence_helpers_accept_only_stable_enum_strings() -> None:
    assert resolve_mode("enforce", PolicyMode.OBSERVE) is PolicyMode.ENFORCE
    assert resolve_mode(None, PolicyMode.OBSERVE) is PolicyMode.OBSERVE
    assert (
        resolve_tier("frontier_max", ModelTier.ECONOMY)
        is ModelTier.FRONTIER_MAX
    )
    assert resolve_tier(None, ModelTier.ECONOMY) is ModelTier.ECONOMY
    with pytest.raises(PolicyValidationError, match="supported ModelTier"):
        resolve_tier("turbo", ModelTier.ECONOMY)


def test_explicit_text_and_file_loaders_return_full_runtime_document() -> None:
    assert 'mode: "off"' in _template_text()

    from_text = load_policy_text(_template_text())
    from_file = load_policy_file(TEMPLATE)
    compatibility = load_adaptive_policy_yaml(_template_text())

    for document in (from_text, from_file, compatibility):
        assert isinstance(document, RuntimePolicyDocument)
        assert document.policy.mode is PolicyMode.OFF
        assert document.catalog.version == 1
        assert set(document.tier_routes) == set(ModelTier)
        assert document.static_fallback == FEATURE_62_STATIC_FALLBACK


def test_loader_never_guesses_that_inline_text_is_a_path() -> None:
    with pytest.raises(
        PolicyValidationError, match="YAML must contain a mapping"
    ):
        load_policy_text(str(TEMPLATE))
    with pytest.raises(PolicyValidationError, match="policy text must be a string"):
        load_adaptive_policy_yaml(TEMPLATE)  # type: ignore[arg-type]


def test_layered_customer_safety_is_monotonic() -> None:
    assert (
        resolve_layered_policy(
            PolicyLayers(
                host=PolicyOverrides(customer_safe=True),
                project=PolicyOverrides(customer_safe=False),
                customer=PolicyOverrides(customer_safe=False),
            )
        ).customer_safe
        is True
    )
    assert (
        resolve_layered_policy(
            PolicyLayers(
                host=PolicyOverrides(customer_safe=False),
                workflow=PolicyOverrides(customer_safe=True),
                customer=PolicyOverrides(customer_safe=False),
            )
        ).customer_safe
        is True
    )
    assert (
        resolve_layered_policy(
            PolicyLayers(
                host=PolicyOverrides(customer_safe=False),
                project=PolicyOverrides(customer_safe=False),
                workflow=PolicyOverrides(customer_safe=False),
                customer=PolicyOverrides(customer_safe=False),
            )
        ).customer_safe
        is False
    )


def test_loaded_layers_catalog_tiers_and_fallback_drive_runtime_resolution() -> None:
    data = _template_data()
    layers = data["layers"]
    tiers = data["tiers"]
    fallback = data["static_fallback"]
    assert isinstance(layers, dict)
    assert isinstance(tiers, dict)
    assert isinstance(fallback, dict)
    host = layers["host"]
    economy = tiers["economy"]
    assert isinstance(host, dict)
    assert isinstance(economy, dict)
    assert isinstance(economy["primary"], dict)

    host["mode"] = "guarded"
    host["default_tier"] = "economy"
    economy["primary"]["reasoning_effort"] = "high"
    document = _load_data(data)
    result = resolve_policy(document)

    assert document.policy.mode is PolicyMode.GUARDED
    assert document.policy.default_tier is ModelTier.ECONOMY
    assert result.selection is not None
    assert result.selection.model_id == "gpt-5.6-luna"
    assert result.selection.reasoning_effort is ReasoningEffort.HIGH

    catalog = data["catalog"]
    assert isinstance(catalog, dict)
    models = catalog["models"]
    assert isinstance(models, list)
    assert isinstance(models[0], dict)
    models[0]["available"] = False
    fallback_result = resolve_policy(_load_data(data))
    assert fallback_result.selection is not None
    assert fallback_result.selection.model_id == "gpt-5.6-terra"
    assert fallback_result.selection.reasoning_effort is ReasoningEffort.HIGH

    host["mode"] = "off"
    fallback["behavior"] = "configured_static_behavior"
    off = resolve_policy(_load_data(data))
    assert off.static_fallback is not None
    assert off.static_fallback.behavior == "configured_static_behavior"


def test_routes_all_policy_modes_and_tiers_deterministically() -> None:
    for mode in (
        PolicyMode.OBSERVE,
        PolicyMode.GUARDED,
        PolicyMode.ENFORCE,
    ):
        for tier in (
            ModelTier.ECONOMY,
            ModelTier.BALANCED,
            ModelTier.FRONTIER,
            ModelTier.FRONTIER_MAX,
        ):
            result = resolve_policy(
                AdaptivePolicy(mode=mode, default_tier=tier)
            )
            assert result.selection is not None
            assert result.tier is tier
            assert result.applied is (mode is not PolicyMode.OBSERVE)


@pytest.mark.parametrize(
    ("tier", "effort"),
    [
        (ModelTier.FRONTIER, ReasoningEffort.HIGH),
        (ModelTier.FRONTIER_MAX, ReasoningEffort.ULTRA),
    ],
)
def test_frontier_routes_select_sol_at_tier_floor(
    tier: ModelTier, effort: ReasoningEffort
) -> None:
    result = resolve_policy(
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=tier)
    )

    assert result.selection is not None
    assert result.selection.model_id == "gpt-5.6-sol"
    assert result.selection.reasoning_effort is effort


def test_unavailable_balanced_primary_uses_only_safe_declared_fallback() -> None:
    fake_catalog = ModelCatalog(
        records=(
            replace(
                DEFAULT_MODEL_CATALOG.get("gpt-5.6-terra"),
                available=False,
            ),  # type: ignore[arg-type]
            DEFAULT_MODEL_CATALOG.get("gpt-5.6-sol"),  # type: ignore[arg-type]
        )
    )

    result = resolve_policy(
        AdaptivePolicy(mode=PolicyMode.GUARDED), catalog=fake_catalog
    )

    assert result.selection is not None
    assert result.selection.model_id == "gpt-5.6-sol"
    assert result.selection.reasoning_effort is ReasoningEffort.MEDIUM


def test_sol_unavailable_frontier_fails_closed_without_terra_downgrade() -> None:
    records = tuple(
        replace(record, available=False)
        if record.model_id == "gpt-5.6-sol"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )

    with pytest.raises(
        CapabilityUnavailableError, match="no approved available model"
    ):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.ENFORCE,
                default_tier=ModelTier.FRONTIER,
            ),
            catalog=ModelCatalog(records),
        )


def test_normal_candidates_enforce_capability_rank_at_resolution() -> None:
    unsafe_routes = dict(TIER_ROUTES)
    unsafe_routes[ModelTier.FRONTIER] = TierRoute(
        ModelTier.FRONTIER,
        (
            ModelCandidate(
                "balanced",
                ReasoningEffort.HIGH,
                TIER_ROUTES[ModelTier.FRONTIER].candidates[0].requirements,
            ),
        ),
    )

    with pytest.raises(
        CapabilityUnavailableError, match="no approved available model"
    ):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.GUARDED,
                default_tier=ModelTier.FRONTIER,
            ),
            tier_routes=unsafe_routes,
        )


def test_new_or_renamed_catalog_records_require_explicit_alias_mapping() -> None:
    unknown_catalog = ModelCatalog(
        records=(
            ModelCapability(
                "gpt-5.6-new",
                (ReasoningEffort.ULTRA,),
                capability_tier=CapabilityTier.BALANCED,
            ),
        )
    )
    with pytest.raises(
        CapabilityUnavailableError, match="no approved available model"
    ):
        resolve_policy(
            AdaptivePolicy(mode=PolicyMode.ENFORCE),
            catalog=unknown_catalog,
        )

    renamed_catalog = ModelCatalog(
        records=(
            ModelCapability(
                "gpt-5.7-renamed",
                TERRA_EFFORTS,
                aliases=("balanced",),
                capability_tier=CapabilityTier.BALANCED,
            ),
        )
    )
    result = resolve_policy(
        AdaptivePolicy(mode=PolicyMode.ENFORCE),
        catalog=renamed_catalog,
    )
    assert result.selection is not None
    assert result.selection.model_id == "gpt-5.7-renamed"


def test_explicit_override_requires_allowlist_capability_and_effort_floor() -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.ENFORCE,
        default_tier=ModelTier.ECONOMY,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"gpt-5.6-luna"}),
    )
    result = resolve_policy(
        policy,
        RoutingRequest(
            model_override="gpt-5.6-luna",
            reasoning_effort=ReasoningEffort.MAX,
        ),
    )

    assert result.selection is not None
    assert result.selection.model_id == "gpt-5.6-luna"
    with pytest.raises(
        CapabilityUnavailableError, match="explicit model override"
    ):
        resolve_policy(
            policy,
            RoutingRequest(
                model_override="gpt-5.6-luna",
                reasoning_effort=ReasoningEffort.ULTRA,
            ),
        )


def test_explicit_luna_override_is_rejected_for_frontier_route() -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.ENFORCE,
        default_tier=ModelTier.FRONTIER,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"gpt-5.6-luna"}),
    )

    with pytest.raises(
        CapabilityUnavailableError, match="below the required capability tier"
    ):
        resolve_policy(
            policy,
            RoutingRequest(model_override="gpt-5.6-luna"),
        )


def test_request_tier_cannot_lower_policy_default_floor() -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.ENFORCE,
        default_tier=ModelTier.FRONTIER,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"gpt-5.6-luna"}),
    )

    with pytest.raises(
        CapabilityUnavailableError, match="below the required capability tier"
    ):
        resolve_policy(
            policy,
            RoutingRequest(
                tier="economy",
                model_override="gpt-5.6-luna",
            ),
        )


def test_frontier_max_cannot_accept_low_effort() -> None:
    with pytest.raises(
        PolicyValidationError, match="below required minimum ultra"
    ):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.GUARDED,
                default_tier=ModelTier.FRONTIER_MAX,
            ),
            RoutingRequest(reasoning_effort="low"),
        )


def test_assessment_floor_blocks_production_economy_override() -> None:
    assessment = assess_task("Deploy this change to production.")
    observed = resolve_policy(
        AdaptivePolicy(
            mode=PolicyMode.OBSERVE,
            default_tier=ModelTier.ECONOMY,
        ),
        RoutingRequest(
            tier="economy",
            assessment_minimum_tier=assessment.minimum_tier,
        ),
    )

    assert observed.tier is ModelTier.HUMAN_GATE
    assert observed.applied is False
    assert observed.human_approval_required is True
    with pytest.raises(HumanApprovalRequiredError):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.GUARDED,
                default_tier=ModelTier.ECONOMY,
            ),
            RoutingRequest(
                tier="economy",
                minimum_tier=assessment.minimum_tier,
            ),
        )


def test_observe_recommends_human_gate_but_enforcing_modes_block() -> None:
    observe = resolve_policy(
        AdaptivePolicy(
            mode=PolicyMode.OBSERVE,
            default_tier=ModelTier.HUMAN_GATE,
        )
    )
    assert observe.selection is not None
    assert observe.selection.model_id == "gpt-5.6-sol"
    assert observe.applied is False
    assert observe.human_approval_required is True
    for mode in (PolicyMode.GUARDED, PolicyMode.ENFORCE):
        with pytest.raises(HumanApprovalRequiredError):
            resolve_policy(
                AdaptivePolicy(
                    mode=mode,
                    default_tier=ModelTier.HUMAN_GATE,
                )
            )


def test_caller_route_cannot_disable_human_gate_approval() -> None:
    unsafe_routes = dict(TIER_ROUTES)
    unsafe_routes[ModelTier.HUMAN_GATE] = replace(
        TIER_ROUTES[ModelTier.HUMAN_GATE],
        requires_human_approval=False,
    )

    with pytest.raises(HumanApprovalRequiredError):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.ENFORCE,
                default_tier=ModelTier.HUMAN_GATE,
            ),
            tier_routes=unsafe_routes,
        )


def test_human_approval_type_and_customer_safety_fail_closed() -> None:
    with pytest.raises(
        PolicyValidationError,
        match="request.human_approved must be a bool",
    ):
        resolve_policy(
            AdaptivePolicy(mode=PolicyMode.GUARDED),
            RoutingRequest(human_approved="false"),  # type: ignore[arg-type]
        )

    errors = validate_policy(
        AdaptivePolicy(customer_safe=False),
        customer_safe_required=True,
    )
    assert errors == (
        "customer-safe routing requires policy.customer_safe=true",
    )
    unsafe_catalog = ModelCatalog(
        records=(
            ModelCapability(
                "unsafe-balanced",
                TERRA_EFFORTS,
                aliases=("balanced",),
                capability_tier=CapabilityTier.BALANCED,
                customer_safe=False,
            ),
        )
    )
    with pytest.raises(
        CapabilityUnavailableError, match="no approved available model"
    ):
        resolve_policy(
            AdaptivePolicy(mode=PolicyMode.GUARDED),
            catalog=unsafe_catalog,
        )
    with pytest.raises(
        CapabilityUnavailableError, match="no approved available model"
    ):
        resolve_policy(
            AdaptivePolicy(
                mode=PolicyMode.GUARDED,
                customer_safe=False,
            ),
            RoutingRequest(customer_safe=True),
            catalog=unsafe_catalog,
        )


def test_duplicate_yaml_keys_are_rejected() -> None:
    duplicate = _template_text().replace(
        "schema_version: 1",
        "schema_version: 1\nschema_version: 1",
        1,
    )

    with pytest.raises(PolicyValidationError, match="duplicate key"):
        load_policy_text(duplicate)


def test_unknown_top_level_section_and_field_keys_are_rejected() -> None:
    mutations = []

    top = _template_data()
    top["unexpected"] = True
    mutations.append(top)

    layer = _template_data()
    layer["layers"]["host"]["unexpected"] = True  # type: ignore[index]
    mutations.append(layer)

    catalog = _template_data()
    catalog["catalog"]["unexpected"] = True  # type: ignore[index]
    mutations.append(catalog)

    model = _template_data()
    model["catalog"]["models"][0]["unexpected"] = True  # type: ignore[index]
    mutations.append(model)

    tier = _template_data()
    tier["tiers"]["economy"]["primary"]["unexpected"] = True  # type: ignore[index]
    mutations.append(tier)

    fallback = _template_data()
    fallback["static_fallback"]["unexpected"] = True  # type: ignore[index]
    mutations.append(fallback)

    for data in mutations:
        with pytest.raises(PolicyValidationError, match="unsupported"):
            _load_data(data)


def test_mixed_legacy_and_layered_policy_forms_are_rejected() -> None:
    data = _template_data()
    data["mode"] = "guarded"

    with pytest.raises(PolicyValidationError, match="cannot mix"):
        _load_data(data)


def test_null_layers_are_rejected_as_an_invalid_layered_form() -> None:
    data = _template_data()
    data["layers"] = None

    with pytest.raises(PolicyValidationError, match="layers must be a mapping"):
        _load_data(data)


def test_null_layers_cannot_bypass_mixed_form_rejection() -> None:
    data = _template_data()
    data["layers"] = None
    data["mode"] = "guarded"

    with pytest.raises(PolicyValidationError, match="cannot mix"):
        _load_data(data)


def test_invalid_types_versions_and_missing_sections_fail_closed() -> None:
    invalid_bool = _template_data()
    invalid_bool["layers"]["host"]["customer_safe"] = "true"  # type: ignore[index]
    with pytest.raises(PolicyValidationError, match="must be a bool"):
        _load_data(invalid_bool)

    invalid_catalog_version = _template_data()
    invalid_catalog_version["catalog"]["version"] = 2  # type: ignore[index]
    with pytest.raises(
        PolicyValidationError, match="unsupported version"
    ):
        _load_data(invalid_catalog_version)

    missing_catalog = _template_data()
    del missing_catalog["catalog"]
    with pytest.raises(
        PolicyValidationError, match="missing required section catalog"
    ):
        _load_data(missing_catalog)


def test_missing_required_tier_is_rejected() -> None:
    data = _template_data()
    del data["tiers"]["frontier_max"]  # type: ignore[index]

    with pytest.raises(
        PolicyValidationError, match="missing required tiers: frontier_max"
    ):
        _load_data(data)


def test_unsafe_tier_capability_and_effort_downgrades_are_rejected() -> None:
    catalog_relabel = _template_data()
    catalog_relabel["catalog"]["models"][1]["capability_tier"] = "frontier"  # type: ignore[index]
    with pytest.raises(
        PolicyValidationError,
        match="gpt-5.6-terra capability_tier must be balanced",
    ):
        _load_data(catalog_relabel)

    capability_downgrade = _template_data()
    capability_downgrade["tiers"]["frontier"]["primary"]["model"] = "balanced"  # type: ignore[index]
    with pytest.raises(
        PolicyValidationError, match="unsafe tier downgrade mapping"
    ):
        _load_data(capability_downgrade)

    effort_downgrade = deepcopy(_template_data())
    effort_downgrade["tiers"]["frontier"]["primary"]["reasoning_effort"] = "medium"  # type: ignore[index]
    with pytest.raises(
        PolicyValidationError, match="unsafe tier effort downgrade"
    ):
        _load_data(effort_downgrade)
