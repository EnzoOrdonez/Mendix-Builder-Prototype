"""Tests para el motor de auditoría de buenas prácticas.

Fase 10: Tests unitarios completos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mendex.auditor.engine import (
    AuditedArtifact,
    AuditEngine,
    AuditReport,
    AuditStatus,
)
from mendex.auditor.rules import (
    AuditFinding,
    AttributeNamingRule,
    EntityAttributeCountRule,
    EntityPascalCaseRule,
    FindingSeverity,
    MicroflowNamingRule,
    ModuleNamingRule,
    PageNamingRule,
    get_default_rules,
)
from mendex.bridge.sdk_client import (
    EntityInfo,
    MockSDKClient,
    ModuleInfo,
    ProjectStructure,
    SDKClientError,
    SecurityInfo,
)
from mendex.logging.decision_logger import DecisionLogger


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mpr_path(tmp_path: Path) -> Path:
    mpr = tmp_path / "test.mpr"
    mpr.write_bytes(b"fake")
    return mpr


@pytest.fixture
def decision_logger(tmp_path: Path) -> DecisionLogger:
    return DecisionLogger(tmp_path / "decisions.jsonl")


def _structure_clean() -> ProjectStructure:
    """Proyecto limpio con naming correcto."""
    return ProjectStructure(
        modules=[
            ModuleInfo(
                name="CRM",
                entities=[
                    EntityInfo(name="Customer", attributes=["Name", "Email", "Phone"]),
                    EntityInfo(name="Order", attributes=["OrderDate", "Total"]),
                ],
                pages=["Customer_Create", "Customer_Overview", "Order_Edit"],
                microflows=["ACT_Customer_Save", "VAL_Order_Validate"],
            ),
        ],
        security=SecurityInfo(roles=["Admin", "User"]),
    )


def _structure_dirty() -> ProjectStructure:
    """Proyecto con varias violaciones de naming y estructura."""
    return ProjectStructure(
        modules=[
            ModuleInfo(
                name="My Module",  # spaces in module name
                entities=[
                    EntityInfo(
                        name="customer_data",  # snake_case entity
                        attributes=[
                            "customer_name",  # snake_case attr
                            "email_address",
                            "PhoneNumber",  # PascalCase (ok)
                        ],
                    ),
                    EntityInfo(
                        name="BigEntity",
                        attributes=[f"Field{i}" for i in range(25)],  # 25 attrs
                    ),
                ],
                pages=["MyRandomPage"],  # no Entity_Action pattern
                microflows=["doSomething"],  # no prefix
            ),
        ],
    )


def _structure_empty() -> ProjectStructure:
    """Proyecto sin artefactos."""
    return ProjectStructure(modules=[])


# ═══════════════════════════════════════════════════════════════
# RULE TESTS
# ═══════════════════════════════════════════════════════════════


class TestEntityPascalCaseRule:
    def test_pascal_case_passes(self):
        rule = EntityPascalCaseRule()
        assert rule.check({"name": "Customer"}) is None

    def test_snake_case_fails(self):
        rule = EntityPascalCaseRule()
        finding = rule.check({"name": "customer_data"})
        assert finding is not None
        assert finding.severity == FindingSeverity.WARNING
        assert "NM-001" in finding.rule_id

    def test_empty_name_critical(self):
        rule = EntityPascalCaseRule()
        finding = rule.check({"name": ""})
        assert finding is not None
        assert finding.severity == FindingSeverity.CRITICAL

    def test_lowercase_start_fails(self):
        rule = EntityPascalCaseRule()
        finding = rule.check({"name": "customer"})
        assert finding is not None

    def test_pascal_with_numbers_passes(self):
        rule = EntityPascalCaseRule()
        assert rule.check({"name": "OrderV2"}) is None

    def test_applies_to_entity_only(self):
        rule = EntityPascalCaseRule()
        assert rule.applies_to("entity")
        assert not rule.applies_to("page")


class TestPageNamingRule:
    def test_valid_create_page(self):
        rule = PageNamingRule()
        assert rule.check({"name": "Customer_Create"}) is None

    def test_valid_overview_page(self):
        rule = PageNamingRule()
        assert rule.check({"name": "Order_Overview"}) is None

    def test_invalid_naming(self):
        rule = PageNamingRule()
        finding = rule.check({"name": "MyRandomPage"})
        assert finding is not None
        assert finding.severity == FindingSeverity.INFO

    def test_empty_page_name(self):
        rule = PageNamingRule()
        finding = rule.check({"name": ""})
        assert finding is not None
        assert finding.severity == FindingSeverity.CRITICAL


class TestMicroflowNamingRule:
    def test_valid_act_prefix(self):
        rule = MicroflowNamingRule()
        assert rule.check({"name": "ACT_Customer_Save"}) is None

    def test_valid_val_prefix(self):
        rule = MicroflowNamingRule()
        assert rule.check({"name": "VAL_Order_Validate"}) is None

    def test_valid_sub_prefix(self):
        rule = MicroflowNamingRule()
        assert rule.check({"name": "SUB_CalculateTotal"}) is None

    def test_invalid_no_prefix(self):
        rule = MicroflowNamingRule()
        finding = rule.check({"name": "doSomething"})
        assert finding is not None
        assert finding.severity == FindingSeverity.WARNING

    def test_empty_name(self):
        rule = MicroflowNamingRule()
        finding = rule.check({"name": ""})
        assert finding is not None
        assert finding.severity == FindingSeverity.CRITICAL


class TestEntityAttributeCountRule:
    def test_normal_count_passes(self):
        rule = EntityAttributeCountRule()
        assert rule.check({"name": "E", "attribute_count": 10}) is None

    def test_approaching_limit_info(self):
        rule = EntityAttributeCountRule()
        finding = rule.check({"name": "E", "attribute_count": 18})
        assert finding is not None
        assert finding.severity == FindingSeverity.INFO

    def test_exceeding_limit_warning(self):
        rule = EntityAttributeCountRule()
        finding = rule.check({"name": "E", "attribute_count": 25})
        assert finding is not None
        assert finding.severity == FindingSeverity.WARNING

    def test_exactly_at_limit_passes(self):
        rule = EntityAttributeCountRule()
        assert rule.check({"name": "E", "attribute_count": 20}) is None


class TestAttributeNamingRule:
    def test_pascal_case_passes(self):
        rule = AttributeNamingRule()
        assert rule.check({"attributes": ["Name", "Email"]}) is None

    def test_snake_case_fails(self):
        rule = AttributeNamingRule()
        finding = rule.check({"attributes": ["customer_name", "Email"]})
        assert finding is not None
        assert "customer_name" in finding.message

    def test_empty_list_passes(self):
        rule = AttributeNamingRule()
        assert rule.check({"attributes": []}) is None


class TestModuleNamingRule:
    def test_valid_module(self):
        rule = ModuleNamingRule()
        assert rule.check({"module": "CRM"}) is None

    def test_spaces_in_module(self):
        rule = ModuleNamingRule()
        finding = rule.check({"module": "My Module"})
        assert finding is not None
        assert finding.severity == FindingSeverity.WARNING


class TestGetDefaultRules:
    def test_returns_all_rules(self):
        rules = get_default_rules()
        assert len(rules) >= 6

    def test_covers_all_artifact_types(self):
        rules = get_default_rules()
        types_covered = set()
        for rule in rules:
            types_covered.update(rule.artifact_types)
        assert "entity" in types_covered
        assert "page" in types_covered
        assert "microflow" in types_covered


# ═══════════════════════════════════════════════════════════════
# AUDIT ENGINE TESTS
# ═══════════════════════════════════════════════════════════════


class TestAuditEngineCleanProject:
    def test_clean_project_passes(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_clean())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert report.status == AuditStatus.PASS
        assert report.total_critical == 0
        assert report.total_warnings == 0

    def test_correct_artifact_count(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_clean())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert len(report.entities) == 2
        assert len(report.pages) == 3
        assert len(report.microflows) == 2


class TestAuditEngineDirtyProject:
    def test_dirty_project_has_findings(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert report.total_findings > 0

    def test_detects_snake_case_entity(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        entity_findings = [
            f for a in report.entities for f in a.findings
            if "NM-001" in f.rule_id
        ]
        assert len(entity_findings) >= 1

    def test_detects_attribute_count(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        st001 = [
            f for a in report.entities for f in a.findings
            if f.rule_id == "ST-001"
        ]
        assert len(st001) >= 1

    def test_detects_page_naming(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        page_findings = [
            f for a in report.pages for f in a.findings
        ]
        assert len(page_findings) >= 1

    def test_detects_microflow_naming(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        mf_findings = [
            f for a in report.microflows for f in a.findings
            if "NM-003" in f.rule_id
        ]
        assert len(mf_findings) >= 1

    def test_detects_module_spaces(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        nm005 = [
            f for a in report.artifacts for f in a.findings
            if f.rule_id == "NM-005"
        ]
        assert len(nm005) >= 1

    def test_status_is_warn_or_fail(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert report.status in (AuditStatus.WARN, AuditStatus.FAIL)


class TestAuditEngineEmptyProject:
    def test_empty_project_passes(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_empty())
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert report.status == AuditStatus.PASS
        assert len(report.artifacts) == 0


class TestAuditEngineSDKError:
    def test_sdk_error_produces_error_report(self, mpr_path: Path):
        sdk = MagicMock()
        sdk.read_project_structure.side_effect = SDKClientError("Connection failed")
        engine = AuditEngine(sdk_client=sdk)
        report = engine.audit(mpr_path, include_bp=False)
        assert report.status == AuditStatus.ERROR
        assert report.scan_error is not None
        assert "Connection failed" in report.scan_error


class TestAuditEngineDecisionLogger:
    def test_logger_called(
        self, mpr_path: Path, decision_logger: DecisionLogger
    ):
        sdk = MockSDKClient(project_structure=_structure_clean())
        engine = AuditEngine(sdk_client=sdk, decision_logger=decision_logger)
        engine.audit(mpr_path, include_bp=False)
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "audit"

    def test_logger_captures_findings(
        self, mpr_path: Path, decision_logger: DecisionLogger
    ):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk, decision_logger=decision_logger)
        engine.audit(mpr_path, include_bp=False)
        entries = decision_logger.read_entries()
        assert len(entries[0].warnings) > 0


class TestAuditEngineCustomRules:
    def test_custom_rules_only(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        # Only use entity naming rule
        engine = AuditEngine(
            sdk_client=sdk,
            rules=[EntityPascalCaseRule()],
        )
        report = engine.audit(mpr_path, include_bp=False)
        # Should only have NM-001 findings
        all_rule_ids = {f.rule_id for a in report.artifacts for f in a.findings}
        assert all_rule_ids <= {"NM-001"}

    def test_empty_rules(self, mpr_path: Path):
        sdk = MockSDKClient(project_structure=_structure_dirty())
        engine = AuditEngine(sdk_client=sdk, rules=[])
        report = engine.audit(mpr_path, include_bp=False)
        assert report.total_findings == 0


# ═══════════════════════════════════════════════════════════════
# REPORT TESTS
# ═══════════════════════════════════════════════════════════════


class TestAuditReport:
    def test_text_report_header(self):
        report = AuditReport(mpr_path="/test.mpr")
        text = report.as_text_report()
        assert "Audit Report" in text
        assert "/test.mpr" in text

    def test_text_report_with_error(self):
        report = AuditReport(mpr_path="/test.mpr", scan_error="Failed")
        text = report.as_text_report()
        assert "ERROR" in text
        assert "Failed" in text

    def test_to_dict_structure(self):
        report = AuditReport(mpr_path="/test.mpr")
        d = report.to_dict()
        assert "status" in d
        assert "artifacts" in d
        assert "summary" in d

    def test_to_json(self):
        report = AuditReport(mpr_path="/test.mpr")
        j = report.to_json()
        import json
        data = json.loads(j)
        assert data["status"] == "pass"

    def test_summary_counts(self):
        report = AuditReport()
        report.artifacts = [
            AuditedArtifact(
                artifact_type="entity",
                name="E1",
                module="M",
                findings=[
                    AuditFinding("R1", FindingSeverity.CRITICAL, "bad"),
                    AuditFinding("R2", FindingSeverity.WARNING, "meh"),
                ],
            ),
            AuditedArtifact(
                artifact_type="page",
                name="P1",
                module="M",
                findings=[
                    AuditFinding("R3", FindingSeverity.INFO, "fyi"),
                ],
            ),
        ]
        assert report.total_critical == 1
        assert report.total_warnings == 1
        assert report.total_info == 1
        assert report.total_findings == 3
        assert report.status == AuditStatus.FAIL


class TestAuditedArtifact:
    def test_has_critical(self):
        a = AuditedArtifact(
            artifact_type="entity", name="E", module="M",
            findings=[AuditFinding("R1", FindingSeverity.CRITICAL, "bad")],
        )
        assert a.has_critical

    def test_max_severity(self):
        a = AuditedArtifact(
            artifact_type="entity", name="E", module="M",
            findings=[
                AuditFinding("R1", FindingSeverity.INFO, "ok"),
                AuditFinding("R2", FindingSeverity.WARNING, "meh"),
            ],
        )
        assert a.max_severity == FindingSeverity.WARNING

    def test_report_lines(self):
        a = AuditedArtifact(
            artifact_type="entity", name="E", module="M",
            findings=[AuditFinding("R1", FindingSeverity.WARNING, "test msg")],
        )
        lines = a.as_report_lines()
        assert any("test msg" in line for line in lines)


class TestAuditFinding:
    def test_to_dict(self):
        f = AuditFinding("R1", FindingSeverity.WARNING, "msg", "fix it")
        d = f.to_dict()
        assert d["rule_id"] == "R1"
        assert d["severity"] == "warning"
        assert d["recommendation"] == "fix it"

    def test_report_line_icons(self):
        f = AuditFinding("R1", FindingSeverity.CRITICAL, "bad")
        assert "✗" in f.as_report_line()

        f2 = AuditFinding("R2", FindingSeverity.WARNING, "meh")
        assert "⚠" in f2.as_report_line()

        f3 = AuditFinding("R3", FindingSeverity.INFO, "fyi")
        assert "ℹ" in f3.as_report_line()
