"""Backend selection per Felix ROUTING.md §2."""

from __future__ import annotations

from app.router import BackendRegistry, is_locked, select_backend


def _make_registry(settings, *, all_models=("qwen3.5:35b-a3b-nvfp4", "gemma4:13b", "gemma4:e4b", "nomic-embed-text")):
    reg = BackendRegistry(settings)
    for b in reg.backends.values():
        b.online = True
        b.models_loaded = list(all_models)
    return reg


def test_locked_model_detection(_settings):
    assert is_locked("qwen3.6:35b", _settings)
    assert is_locked("qwen3.6:latest", _settings)
    assert is_locked("qwen3.6:35b-a3b-nvfp4", _settings)
    assert not is_locked("qwen3.5:35b-a3b-nvfp4", _settings)


def test_m5_max_first_when_serves(_settings):
    reg = _make_registry(_settings)
    decision = select_backend("qwen3.5:35b-a3b-nvfp4", reg, _settings)
    assert decision.backend.name == "m5-max"


def test_unknown_model_yields_no_backend(_settings):
    """Per ROUTING.md §2.2 step 1: only backends that .serves(model) are eligible."""
    reg = _make_registry(_settings)
    decision = select_backend("brand-new-model", reg, _settings)
    assert decision.backend is None
    assert decision.reason_if_none == "no_serving_backend"


def test_m5_max_at_cap_falls_to_m5_pro(_settings):
    reg = _make_registry(_settings)
    reg.backends["m5-max"].queue_depth = 2  # at cap
    decision = select_backend("qwen3.5:35b-a3b-nvfp4", reg, _settings)
    assert decision.backend.name == "m5-pro"


def test_m5_pro_cap_is_one(_settings):
    """m5-pro queue cap is 1 per ROUTING.md §2.1; both backends at cap triggers soft-cap relaxation."""
    reg = _make_registry(_settings)
    reg.backends["m5-max"].queue_depth = 2  # at cap
    reg.backends["m5-pro"].queue_depth = 1  # at cap
    decision = select_backend("gemma4:13b", reg, _settings)
    # Both at hard cap. Step 3 relaxes to 2x; m5-pro has lower depth (1) so it wins.
    assert decision.backend is not None
    assert decision.backend.name == "m5-pro"


def test_all_offline_returns_none(_settings):
    reg = _make_registry(_settings)
    for b in reg.backends.values():
        b.online = False
    decision = select_backend("qwen3.5:35b-a3b-nvfp4", reg, _settings)
    assert decision.backend is None
    assert decision.reason_if_none == "no_serving_backend"


def test_exclude_skips_backend(_settings):
    reg = _make_registry(_settings)
    decision = select_backend(
        "qwen3.5:35b-a3b-nvfp4", reg, _settings, exclude={"m5-max"}
    )
    assert decision.backend.name == "m5-pro"
