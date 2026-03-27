"""Tests para el motor de dry-run, idempotency checker y veredictos BP.

Fase 5: Tests unitarios completos.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mendex.bridge.sdk_client import MockSDKClient
from mendex.knowledge.bp_evaluator import BPEvaluation
from mendex.logging.decision_logger import BPVerdict, DecisionLogger
from mendex.orchestrator.dry_run import (
    ArtifactType,
    ConflictPolicy,
    ConflictStatus,
    DryRunArtifact,
    DryRunEngine,
    DryRunReport,
)
from mendex.schema.intermediate import (
    AccessRuleSchema,
    AttributeSchema,
    EntitySchema,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    MicroflowSchema,
    MicroflowType,
    PageSchema,
    PageType,
)


# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mpr_path(tmp_path: Path) -> Path:
    """Path ficticio a un .mpr para tests."""
    mpr = tmp_path / "test_project.mpr"
    mpr.write_bytes(b"fake mpr content")
    return mpr


@pytest.fixture
def mock_sdk() -> MockSDKClient:
    """SDK client mock sin artefactos existentes."""
    return MockSDKClient(existing_artifacts=set())


@pytest.fixture
def mock_sdk_with_existing() -> MockSDKClient:
    """SDK client mock con artefactos existentes."""
    return MockSDKClient(
        existing_artifacts={
            "entity:Operaciones.OrdenCompra",
            "page:Operaciones.OrdenCompra_NewEdit",
            "microflow:Operaciones.ACT_OrdenCompra_Guardar",
        }
    )


@pytest.fixture
def decision_logger(tmp_path: Path) -> DecisionLogger:
    """Decision logger que escribe a directorio temporal."""
    return DecisionLogger(tmp_path / "decisions.jsonl")


def _make_bp_evaluation(
    verdict: BPVerdict = BPVerdict.CONFORME,
    confidence: float = 0.9,
    reason: str = "Cumple las BP oficiales",
    recommendation: str | None = None,
    convention_conflict: str | None = None,
) -> BPEvaluation:
    """Factory para BPEvaluation en tests."""
    return BPEvaluation(
        verdict=verdict,
        confidence=confidence,
        reason=reason,
        recommendation=recommendation,
        convention_conflict=convention_conflict,
    )


def _make_mock_bp_evaluator(
    verdict: BPVerdict = BPVerdict.CONFORME,
) -> MagicMock:
    """Crea un BPEvaluator mock que siempre retorna el mismo veredicto."""
    evaluator = MagicMock()
    evaluator.evaluate.return_value = _make_bp_evaluation(verdict=verdict)
    return evaluator


def _make_entity(
    name: str = "OrdenCompra",
    module: str = "Operaciones",
    n_attributes: int = 3,
    with_access_rules: bool = False,
) -> EntitySchema:
    """Factory para EntitySchema en tests."""
    attrs = [
        AttributeSchema(
            name=f"Campo{i}",
            mendix_type=MendixDataType.STRING,
            label=f"Campo {i}",
        )
        for i in range(1, n_attributes + 1)
    ]
    rules = []
    if with_access_rules:
        rules = [
            AccessRuleSchema(role="Administrator", can_create=True, can_read=True, can_write=True),
            AccessRuleSchema(role="User", can_read=True),
        ]
    return EntitySchema(name=name, module=module, attributes=attrs, access_rules=rules)


def _make_page(
    name: str = "OrdenCompra_NewEdit",
    module: str = "Operaciones",
    entity: str = "OrdenCompra",
    page_type: PageType = PageType.CREATE,
) -> PageSchema:
    return PageSchema(
        name=name, page_type=page_type, entity=entity, module=module
    )


def _make_microflow(
    name: str = "ACT_OrdenCompra_Guardar",
    module: str = "Operaciones",
    entity: str = "OrdenCompra",
    mf_type: MicroflowType = MicroflowType.SAVE,
) -> MicroflowSchema:
    return MicroflowSchema(
        name=name,
        microflow_type=mf_type,
        entity=entity,
        module=module,
        logic_description="Guardar la orden de compra",
    )


def _make_schema(
    entities: list[EntitySchema] | None = None,
    pages: list[PageSchema] | None = None,
    microflows: list[MicroflowSchema] | None = None,
) -> IntermediateSchema:
    return IntermediateSchema(
        source=InputSource.EXCEL,
        source_file="test.xlsx",
        entities=entities or [],
        pages=pages or [],
        microflows=microflows or [],
    )


# ─── Tests: DryRunArtifact ────────────────────────────────────


class TestDryRunArtifact:
    """Tests para el modelo DryRunArtifact."""

    def test_bp_verdict_with_evaluation(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="Test",
            module="Mod",
            bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
        )
        assert artifact.bp_verdict == BPVerdict.CONFORME

    def test_bp_verdict_without_evaluation(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="Test",
            module="Mod",
        )
        assert artifact.bp_verdict == BPVerdict.SIN_DATOS

    def test_report_lines_entity_conforme(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="OrdenCompra",
            module="Operaciones",
            bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
        )
        lines = artifact.as_report_lines(1)
        assert 'Entity "OrdenCompra"' in lines
        assert '"Operaciones"' in lines
        assert "CONFORME" in lines
        assert "✓" in lines

    def test_report_lines_page(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.PAGE,
            name="OrdenCompra_NewEdit",
            module="Operaciones",
            bp_evaluation=_make_bp_evaluation(BPVerdict.SIN_DATOS, reason="Sin datos"),
        )
        lines = artifact.as_report_lines(2)
        assert 'Page "OrdenCompra_NewEdit"' in lines
        assert "SIN_DATOS" in lines

    def test_report_lines_microflow(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.MICROFLOW,
            name="ACT_Test_Save",
            module="Mod",
        )
        lines = artifact.as_report_lines(3)
        assert 'Microflow "ACT_Test_Save"' in lines

    def test_report_lines_no_conforme_with_recommendation(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="test_entity",
            module="Mod",
            bp_evaluation=_make_bp_evaluation(
                BPVerdict.NO_CONFORME,
                reason="Usa snake_case",
                recommendation="Usar PascalCase",
            ),
        )
        lines = artifact.as_report_lines(1)
        assert "NO_CONFORME" in lines
        assert "✗" in lines
        assert "Recomendación: Usar PascalCase" in lines

    def test_report_lines_convention_conflict(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="Test",
            module="Mod",
            bp_evaluation=_make_bp_evaluation(
                BPVerdict.NO_CONFORME,
                convention_conflict="Convención del proyecto usa prefijo diferente",
            ),
        )
        lines = artifact.as_report_lines(1)
        assert "Conflicto convenciones" in lines

    def test_report_lines_skip_conflict(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="OrdenCompra",
            module="Mod",
            conflict=ConflictStatus.EXISTS_SKIP,
            will_execute=False,
        )
        lines = artifact.as_report_lines(1)
        assert "SKIP" in lines
        assert "NO se ejecutará" in lines

    def test_report_lines_overwrite_conflict(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="OrdenCompra",
            module="Mod",
            conflict=ConflictStatus.EXISTS_OVERWRITE,
        )
        lines = artifact.as_report_lines(1)
        assert "OVERWRITE" in lines

    def test_report_lines_warnings(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="Test",
            module="Mod",
            warnings=["Sin access rules", "Demasiados atributos"],
        )
        lines = artifact.as_report_lines(1)
        assert "Sin access rules" in lines
        assert "Demasiados atributos" in lines

    def test_report_lines_not_executing(self):
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name="Test",
            module="Mod",
            will_execute=False,
        )
        lines = artifact.as_report_lines(1)
        assert "NO se ejecutará" in lines


# ─── Tests: DryRunReport ──────────────────────────────────────


class TestDryRunReport:
    """Tests para el modelo DryRunReport."""

    def test_empty_report(self):
        report = DryRunReport()
        assert report.total_conforme == 0
        assert report.total_no_conforme == 0
        assert report.total_sin_datos == 0
        assert report.total_conflicts == 0
        assert report.total_will_execute == 0
        assert not report.has_no_conforme
        assert not report.aborted

    def test_summary_properties(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E1",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
                ),
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E2",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.NO_CONFORME),
                ),
                DryRunArtifact(
                    artifact_type=ArtifactType.PAGE,
                    name="P1",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.SIN_DATOS),
                ),
                DryRunArtifact(
                    artifact_type=ArtifactType.MICROFLOW,
                    name="MF1",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
                    conflict=ConflictStatus.EXISTS_SKIP,
                    will_execute=False,
                ),
            ]
        )
        assert report.total_conforme == 2
        assert report.total_no_conforme == 1
        assert report.total_sin_datos == 1
        assert report.total_conflicts == 1
        assert report.total_will_execute == 3
        assert report.has_no_conforme

    def test_entities_pages_microflows_filters(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(artifact_type=ArtifactType.ENTITY, name="E1", module="M"),
                DryRunArtifact(artifact_type=ArtifactType.ENTITY, name="E2", module="M"),
                DryRunArtifact(artifact_type=ArtifactType.PAGE, name="P1", module="M"),
                DryRunArtifact(artifact_type=ArtifactType.MICROFLOW, name="MF1", module="M"),
            ]
        )
        assert len(report.entities) == 2
        assert len(report.pages) == 1
        assert len(report.microflows) == 1

    def test_text_report_contains_header(self):
        report = DryRunReport()
        text = report.as_text_report()
        assert "MendixFormAgent" in text
        assert "Dry-Run Report" in text

    def test_text_report_aborted(self):
        report = DryRunReport(
            aborted=True,
            abort_reason="Strict mode violation",
        )
        text = report.as_text_report()
        assert "ABORTADO" in text
        assert "Strict mode violation" in text

    def test_text_report_strict_mode_label(self):
        report = DryRunReport(strict_mode=True)
        text = report.as_text_report()
        assert "--strict" in text

    def test_text_report_conflict_policy(self):
        report = DryRunReport(conflict_policy=ConflictPolicy.OVERWRITE)
        text = report.as_text_report()
        assert "--on-conflict=overwrite" in text

    def test_text_report_shows_artifacts(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="OrdenCompra",
                    module="Operaciones",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
                ),
            ]
        )
        text = report.as_text_report()
        assert "OrdenCompra" in text
        assert "CONFORME" in text

    def test_text_report_summary_line(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E1",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
                ),
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E2",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.NO_CONFORME),
                ),
            ]
        )
        text = report.as_text_report()
        assert "1 CONFORME" in text
        assert "1 NO_CONFORME" in text

    def test_to_dict_structure(self):
        report = DryRunReport(
            conflict_policy=ConflictPolicy.SKIP,
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E1",
                    module="M",
                    bp_evaluation=_make_bp_evaluation(BPVerdict.CONFORME),
                ),
            ],
        )
        d = report.to_dict()
        assert d["status"] == "dry_run_complete"
        assert d["conflict_policy"] == "skip"
        assert d["strict_mode"] is False
        assert len(d["artifacts"]) == 1
        assert d["artifacts"][0]["type"] == "entity"
        assert d["artifacts"][0]["name"] == "E1"
        assert d["artifacts"][0]["bp_verdict"] == "CONFORME"
        assert d["summary"]["total"] == 1
        assert d["summary"]["conforme"] == 1

    def test_to_dict_aborted(self):
        report = DryRunReport(aborted=True, abort_reason="test reason")
        d = report.to_dict()
        assert d["status"] == "aborted"
        assert d["abort_reason"] == "test reason"

    def test_to_json_valid(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="E1",
                    module="M",
                ),
            ],
        )
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert parsed["summary"]["total"] == 1

    def test_to_json_unicode(self):
        report = DryRunReport(
            artifacts=[
                DryRunArtifact(
                    artifact_type=ArtifactType.ENTITY,
                    name="Dirección",
                    module="Módulo",
                    warnings=["Atención: nombre con acentos"],
                ),
            ],
        )
        json_str = report.to_json()
        assert "Dirección" in json_str
        assert "Módulo" in json_str


# ─── Tests: DryRunEngine — basic ──────────────────────────────


class TestDryRunEngineBasic:
    """Tests básicos del DryRunEngine."""

    def test_empty_schema(self, mock_sdk: MockSDKClient, mpr_path: Path):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema()
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 0
        assert not report.aborted

    def test_single_entity_no_bp(self, mock_sdk: MockSDKClient, mpr_path: Path):
        """Sin BPEvaluator, el bp_evaluation es None → SIN_DATOS."""
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 1
        assert report.artifacts[0].artifact_type == ArtifactType.ENTITY
        assert report.artifacts[0].name == "OrdenCompra"
        assert report.artifacts[0].bp_verdict == BPVerdict.SIN_DATOS
        assert report.artifacts[0].will_execute is True

    def test_single_entity_conforme(self, mock_sdk: MockSDKClient, mpr_path: Path):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert report.total_conforme == 1
        assert report.total_no_conforme == 0

    def test_single_entity_no_conforme(self, mock_sdk: MockSDKClient, mpr_path: Path):
        evaluator = _make_mock_bp_evaluator(BPVerdict.NO_CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity(name="orden_compra")])
        report = engine.run(schema, mpr_path)
        assert report.total_no_conforme == 1
        assert report.has_no_conforme

    def test_multiple_artifact_types(self, mock_sdk: MockSDKClient, mpr_path: Path):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
            microflows=[_make_microflow()],
        )
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 3
        assert len(report.entities) == 1
        assert len(report.pages) == 1
        assert len(report.microflows) == 1

    def test_entity_without_access_rules_warning(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(entities=[_make_entity(with_access_rules=False)])
        report = engine.run(schema, mpr_path)
        warnings = report.artifacts[0].warnings
        assert any("access rules" in w.lower() or "acceso" in w.lower() for w in warnings)

    def test_entity_with_access_rules_no_warning(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        entity = _make_entity(with_access_rules=True)
        schema = _make_schema(entities=[entity])
        report = engine.run(schema, mpr_path)
        warnings = report.artifacts[0].warnings
        assert not any("access rules" in w.lower() or "acceso" in w.lower() for w in warnings)

    def test_entity_many_attributes_warning(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        entity = _make_entity(n_attributes=25)
        schema = _make_schema(entities=[entity])
        report = engine.run(schema, mpr_path)
        warnings = report.artifacts[0].warnings
        assert any("25 atributos" in w for w in warnings)

    def test_entity_few_attributes_no_warning(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        entity = _make_entity(n_attributes=5)
        schema = _make_schema(entities=[entity])
        report = engine.run(schema, mpr_path)
        warnings = report.artifacts[0].warnings
        assert not any("atributos" in w and "máximo" in w for w in warnings)


# ─── Tests: Idempotency / Conflict Resolution ─────────────────


class TestDryRunIdempotency:
    """Tests para idempotency check y resolución de conflictos."""

    def test_no_conflict_when_not_exists(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert report.artifacts[0].conflict == ConflictStatus.NONE
        assert report.artifacts[0].will_execute is True

    def test_skip_policy_on_existing_entity(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.SKIP)
        assert report.artifacts[0].conflict == ConflictStatus.EXISTS_SKIP
        assert report.artifacts[0].will_execute is False
        assert report.total_conflicts == 1

    def test_overwrite_policy_on_existing_entity(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(
            schema, mpr_path, conflict_policy=ConflictPolicy.OVERWRITE
        )
        assert report.artifacts[0].conflict == ConflictStatus.EXISTS_OVERWRITE
        assert report.artifacts[0].will_execute is True  # overwrite still executes

    def test_abort_policy_on_existing_entity(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
        )
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.ABORT)
        assert report.aborted
        assert "OrdenCompra" in report.abort_reason
        # Abort stops processing: only the first entity is in the report
        assert len(report.artifacts) == 1

    def test_abort_on_page_conflict(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        """Abort also triggers on page collisions."""
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        # Entity does NOT exist, but page does
        schema = _make_schema(
            entities=[_make_entity(name="NuevaEntidad", module="NuevoMod")],
            pages=[_make_page()],
        )
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.ABORT)
        assert report.aborted
        assert "OrdenCompra_NewEdit" in report.abort_reason

    def test_abort_on_microflow_conflict(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        schema = _make_schema(
            entities=[_make_entity(name="NuevaEntidad", module="NuevoMod")],
            pages=[_make_page(name="NuevaPagina", module="NuevoMod")],
            microflows=[_make_microflow()],
        )
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.ABORT)
        assert report.aborted
        assert "ACT_OrdenCompra_Guardar" in report.abort_reason

    def test_no_abort_when_no_conflict(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
        )
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.ABORT)
        assert not report.aborted

    def test_skip_multiple_existing_artifacts(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk_with_existing)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
            microflows=[_make_microflow()],
        )
        report = engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.SKIP)
        assert not report.aborted
        assert report.total_conflicts == 3
        assert report.total_will_execute == 0

    def test_sdk_error_on_check_treated_as_not_exists(
        self, mpr_path: Path
    ):
        """Si el SDK falla en check_artifact_exists, se trata como no existente."""
        sdk = MagicMock()
        sdk.check_artifact_exists.side_effect = Exception("SDK error")
        engine = DryRunEngine(sdk_client=sdk)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert report.artifacts[0].conflict == ConflictStatus.NONE


# ─── Tests: Strict Mode ───────────────────────────────────────


class TestDryRunStrictMode:
    """Tests para el modo --strict."""

    def test_strict_aborts_on_no_conforme(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.NO_CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path, strict=True)
        assert report.aborted
        assert "strict" in report.abort_reason.lower()
        assert "NO_CONFORME" in report.abort_reason

    def test_strict_does_not_abort_on_conforme(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path, strict=True)
        assert not report.aborted

    def test_strict_does_not_abort_on_sin_datos(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.SIN_DATOS)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path, strict=True)
        assert not report.aborted

    def test_strict_lists_all_no_conforme_names(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.NO_CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(
            entities=[
                _make_entity(name="bad_entity_1"),
                _make_entity(name="bad_entity_2"),
            ],
        )
        report = engine.run(schema, mpr_path, strict=True)
        assert report.aborted
        assert "bad_entity_1" in report.abort_reason
        assert "bad_entity_2" in report.abort_reason

    def test_strict_false_does_not_abort(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.NO_CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path, strict=False)
        assert not report.aborted
        assert report.has_no_conforme


# ─── Tests: BP Evaluation Integration ─────────────────────────


class TestDryRunBPEvaluation:
    """Tests para la integración con BPEvaluator."""

    def test_bp_evaluator_called_per_artifact(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
            microflows=[_make_microflow()],
        )
        engine.run(schema, mpr_path)
        assert evaluator.evaluate.call_count == 3

    def test_bp_evaluator_error_graceful(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        """Si BPEvaluator falla, el artefacto se procesa sin evaluación."""
        evaluator = MagicMock()
        evaluator.evaluate.side_effect = Exception("LLM error")
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert report.artifacts[0].bp_evaluation is None
        assert report.artifacts[0].bp_verdict == BPVerdict.SIN_DATOS

    def test_mixed_verdicts(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        """Diferentes artefactos pueden tener diferentes veredictos."""
        evaluator = MagicMock()
        evaluator.evaluate.side_effect = [
            _make_bp_evaluation(BPVerdict.CONFORME),
            _make_bp_evaluation(BPVerdict.NO_CONFORME),
            _make_bp_evaluation(BPVerdict.SIN_DATOS),
        ]
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
            microflows=[_make_microflow()],
        )
        report = engine.run(schema, mpr_path)
        assert report.total_conforme == 1
        assert report.total_no_conforme == 1
        assert report.total_sin_datos == 1

    def test_entity_bp_pattern_includes_naming(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        """Verifica que el patrón de evaluación de entidad incluye info de naming."""
        evaluator = MagicMock()
        evaluator.evaluate.return_value = _make_bp_evaluation()
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity(name="OrdenCompra")])
        engine.run(schema, mpr_path)

        call_args = evaluator.evaluate.call_args
        pattern = call_args[0][0]  # first positional arg
        assert "OrdenCompra" in pattern
        assert "PascalCase" in pattern

    def test_entity_snake_case_detected(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = _make_bp_evaluation()
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(entities=[_make_entity(name="orden_compra")])
        engine.run(schema, mpr_path)

        call_args = evaluator.evaluate.call_args
        pattern = call_args[0][0]
        assert "snake_case" in pattern


# ─── Tests: Decision Logger Integration ───────────────────────


class TestDryRunDecisionLogger:
    """Tests para la integración con DecisionLogger."""

    def test_logger_called_on_complete(
        self,
        mock_sdk: MockSDKClient,
        mpr_path: Path,
        decision_logger: DecisionLogger,
    ):
        engine = DryRunEngine(
            sdk_client=mock_sdk, decision_logger=decision_logger
        )
        schema = _make_schema(entities=[_make_entity()])
        engine.run(schema, mpr_path, input_hash="test123")
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "dry_run"
        assert entries[0].input_hash == "test123"
        assert entries[0].action_taken == "dry_run_complete"

    def test_logger_records_abort(
        self,
        mock_sdk_with_existing: MockSDKClient,
        mpr_path: Path,
        decision_logger: DecisionLogger,
    ):
        engine = DryRunEngine(
            sdk_client=mock_sdk_with_existing,
            decision_logger=decision_logger,
        )
        schema = _make_schema(entities=[_make_entity()])
        engine.run(schema, mpr_path, conflict_policy=ConflictPolicy.ABORT)
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].action_taken == "aborted"

    def test_logger_records_strict_abort(
        self,
        mock_sdk: MockSDKClient,
        mpr_path: Path,
        decision_logger: DecisionLogger,
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.NO_CONFORME)
        engine = DryRunEngine(
            sdk_client=mock_sdk,
            bp_evaluator=evaluator,
            decision_logger=decision_logger,
        )
        schema = _make_schema(entities=[_make_entity()])
        engine.run(schema, mpr_path, strict=True)
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].action_taken == "aborted"

    def test_logger_extra_has_summary(
        self,
        mock_sdk: MockSDKClient,
        mpr_path: Path,
        decision_logger: DecisionLogger,
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(
            sdk_client=mock_sdk,
            bp_evaluator=evaluator,
            decision_logger=decision_logger,
        )
        schema = _make_schema(
            entities=[_make_entity()],
            pages=[_make_page()],
        )
        engine.run(schema, mpr_path)
        entries = decision_logger.read_entries()
        extra = entries[0].extra
        assert extra["total_artifacts"] == 2
        assert extra["conforme"] == 2

    def test_no_logger_no_error(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        """Sin logger, no hay error."""
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(entities=[_make_entity()])
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 1


# ─── Tests: Enums ─────────────────────────────────────────────


class TestDryRunEnums:
    """Tests para los enums del módulo dry_run."""

    def test_conflict_policy_values(self):
        assert ConflictPolicy.SKIP.value == "skip"
        assert ConflictPolicy.OVERWRITE.value == "overwrite"
        assert ConflictPolicy.ABORT.value == "abort"

    def test_artifact_type_values(self):
        assert ArtifactType.ENTITY.value == "entity"
        assert ArtifactType.PAGE.value == "page"
        assert ArtifactType.MICROFLOW.value == "microflow"

    def test_conflict_status_values(self):
        assert ConflictStatus.NONE.value == "none"
        assert ConflictStatus.EXISTS_SKIP.value == "exists_skip"
        assert ConflictStatus.EXISTS_OVERWRITE.value == "exists_overwrite"
        assert ConflictStatus.EXISTS_ABORT.value == "exists_abort"

    def test_resolve_conflict_mapping(self):
        assert DryRunEngine._resolve_conflict(ConflictPolicy.SKIP) == ConflictStatus.EXISTS_SKIP
        assert DryRunEngine._resolve_conflict(ConflictPolicy.OVERWRITE) == ConflictStatus.EXISTS_OVERWRITE
        assert DryRunEngine._resolve_conflict(ConflictPolicy.ABORT) == ConflictStatus.EXISTS_ABORT


# ─── Tests: Edge Cases ────────────────────────────────────────


class TestDryRunEdgeCases:
    """Tests para casos borde."""

    def test_multiple_entities_same_module(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = _make_mock_bp_evaluator(BPVerdict.CONFORME)
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        schema = _make_schema(
            entities=[
                _make_entity(name="Entidad1"),
                _make_entity(name="Entidad2"),
                _make_entity(name="Entidad3"),
            ],
        )
        report = engine.run(schema, mpr_path)
        assert len(report.entities) == 3
        assert all(a.will_execute for a in report.artifacts)

    def test_schema_with_only_pages(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(pages=[_make_page()])
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 1
        assert report.artifacts[0].artifact_type == ArtifactType.PAGE

    def test_schema_with_only_microflows(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        schema = _make_schema(microflows=[_make_microflow()])
        report = engine.run(schema, mpr_path)
        assert len(report.artifacts) == 1
        assert report.artifacts[0].artifact_type == ArtifactType.MICROFLOW

    def test_report_generated_at_is_set(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        report = engine.run(_make_schema(), mpr_path)
        assert report.generated_at is not None

    def test_default_conflict_policy_is_skip(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        engine = DryRunEngine(sdk_client=mock_sdk)
        report = engine.run(_make_schema(), mpr_path)
        assert report.conflict_policy == ConflictPolicy.SKIP

    def test_entity_non_persistable(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = _make_bp_evaluation()
        engine = DryRunEngine(sdk_client=mock_sdk, bp_evaluator=evaluator)
        entity = _make_entity()
        entity.is_persistable = False
        schema = _make_schema(entities=[entity])
        engine.run(schema, mpr_path)
        pattern = evaluator.evaluate.call_args[0][0]
        assert "non-persistable" in pattern
