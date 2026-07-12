from app.registry import registry_from_provider_dicts
from app.validation import scanner
from app.validation.health import HealthResult


def test_registry_manual_off_defaults_to_disabled_state():
    providers = [{
        "name": "p1", "tier": 2, "base_url": "http://x/v1",
        "models": [
            {"id": "p1/on", "enabled": True},
            {"id": "p1/off-legacy", "enabled": False},                       # no flag → manual
            {"id": "p1/off-auto", "enabled": False, "manual_off": False},    # health verdict
            {"id": "p1/off-manual", "enabled": False, "manual_off": True},   # user choice
        ],
    }]

    by_id = {model.id: model for model in registry_from_provider_dicts(providers).models}

    assert by_id["p1/on"].manual_off is False
    assert by_id["p1/off-legacy"].manual_off is True
    assert by_id["p1/off-auto"].manual_off is False
    assert by_id["p1/off-manual"].manual_off is True


def test_scan_registry_skips_only_manual_off(monkeypatch, tmp_path):
    config = tmp_path / "providers.yaml"
    config.write_text(
        """
providers:
  - name: p1
    tier: 2
    base_url: http://x/v1
    api_key_env: ""
    models:
      - {id: p1/on, enabled: true}
      - {id: p1/off-auto, enabled: false, manual_off: false}
      - {id: p1/off-manual, enabled: false, manual_off: true}
""",
        encoding="utf-8",
    )
    scanned = []

    def fake_scan(model, timeout=30.0):
        scanned.append(model.id)
        return HealthResult(model.id, "healthy", 200, 1)

    monkeypatch.setattr(scanner, "scan_model", fake_scan)

    scanner.scan_registry(str(config))

    # Auto-off models keep being scanned (so they can recover); manual off never is.
    assert sorted(scanned) == ["p1/off-auto", "p1/on"]
