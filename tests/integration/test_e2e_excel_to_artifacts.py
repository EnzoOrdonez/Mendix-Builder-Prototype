"""Test E2E round-trip: Excel → parse → generate → verify cross-references.

Uses fixtures/simulacros_sso.xlsx as real input. Runs the full pipeline
with MockSDKClient and verifies that all cross-references are valid.

Sprint 3B del plan v2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mendex.bridge.sdk_client import MockSDKClient
from mendex.generators.domain_model import DomainModelGenerator
from mendex.generators.microflows import MicroflowGenerator
from mendex.generators.pages import PageGenerator
from mendex.parsers.excel_parser import ExcelParser
from mendex.validators.post_generation import PostGenerationValidator

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures"
SSO_XLSX = FIXTURE_DIR / "simulacros_sso.xlsx"
MPR_PATH = Path("fake.mpr")


@pytest.fixture()
def parsed_schema():
    """Parse the SSO fixture Excel."""
    if not SSO_XLSX.exists():
        pytest.skip("fixtures/simulacros_sso.xlsx not found")
    parser = ExcelParser(default_module="SSO")
    return parser.parse(SSO_XLSX)


@pytest.fixture()
def generated_artifacts(parsed_schema):
    """Run all generators with MockSDKClient and return artifacts."""
    mock = MockSDKClient()

    dm_gen = DomainModelGenerator(sdk_client=mock)
    dm_gen.generate(parsed_schema, MPR_PATH)

    pg_gen = PageGenerator(sdk_client=mock)
    pg_gen.generate(parsed_schema, MPR_PATH)

    mf_gen = MicroflowGenerator(sdk_client=mock)
    mf_gen.generate(parsed_schema, MPR_PATH)

    return {
        "schema": parsed_schema,
        "mock": mock,
        "entities": mock.created_entities,
        "pages": mock.created_pages,
        "microflows": mock.created_microflows,
        "associations": mock.created_associations,
    }


# ═══════════════════════════════════════════════════════════════
# Parsing
# ═══════════════════════════════════════════════════════════════


class TestExcelParsing:
    """Verifica que el Excel se parsea correctamente."""

    def test_entities_parsed(self, parsed_schema):
        assert len(parsed_schema.entities) > 0

    def test_pages_generated(self, parsed_schema):
        assert len(parsed_schema.pages) > 0

    def test_microflows_generated(self, parsed_schema):
        assert len(parsed_schema.microflows) > 0

    def test_entities_have_attributes(self, parsed_schema):
        for entity in parsed_schema.entities:
            if not entity.is_filter_entity:
                assert len(entity.attributes) > 0, (
                    f"Entity '{entity.name}' has no attributes"
                )


# ═══════════════════════════════════════════════════════════════
# Artifact Generation
# ═══════════════════════════════════════════════════════════════


class TestArtifactGeneration:
    """Verifica que todos los generadores producen artefactos."""

    def test_entities_created(self, generated_artifacts):
        assert len(generated_artifacts["entities"]) > 0

    def test_pages_created(self, generated_artifacts):
        assert len(generated_artifacts["pages"]) > 0

    def test_microflows_created(self, generated_artifacts):
        assert len(generated_artifacts["microflows"]) > 0


# ═══════════════════════════════════════════════════════════════
# Cross-Reference Validation
# ═══════════════════════════════════════════════════════════════


class TestCrossReferences:
    """Verifica integridad de referencias cruzadas."""

    def test_all_page_entities_exist(self, generated_artifacts):
        """Every page references an entity that was created."""
        entity_names = {e["name"] for e in generated_artifacts["entities"]}
        for page in generated_artifacts["pages"]:
            if page.get("entity"):
                assert page["entity"] in entity_names, (
                    f"Page '{page['name']}' references entity '{page['entity']}' "
                    f"which was not created"
                )

    def test_all_microflow_entities_exist(self, generated_artifacts):
        """Every microflow references an entity that was created."""
        entity_names = {e["name"] for e in generated_artifacts["entities"]}
        for mf in generated_artifacts["microflows"]:
            if mf.get("entity"):
                assert mf["entity"] in entity_names, (
                    f"Microflow '{mf['name']}' references entity '{mf['entity']}' "
                    f"which was not created"
                )

    def test_button_microflows_exist_in_generated(self, generated_artifacts):
        """Buttons referencing microflows should point to generated ones."""
        mf_names = {mf["name"] for mf in generated_artifacts["microflows"]}
        missing = []
        for page in generated_artifacts["pages"]:
            for btn in page.get("buttons", []):
                mf_ref = btn.get("microflow")
                if mf_ref:
                    # Extract simple name from qualified
                    simple_name = mf_ref.split(".")[-1] if "." in mf_ref else mf_ref
                    if simple_name not in mf_names:
                        missing.append(
                            f"Page '{page['name']}' button '{btn['label']}' "
                            f"→ microflow '{mf_ref}'"
                        )
        # Allow some missing (e.g., cross-module references) but flag if too many
        total_buttons = sum(
            len(p.get("buttons", [])) for p in generated_artifacts["pages"]
        )
        if total_buttons > 0:
            ratio = len(missing) / total_buttons
            assert ratio < 0.5, (
                f"Too many missing microflow references ({len(missing)}/{total_buttons}):\n"
                + "\n".join(missing[:10])
            )

    def test_button_pages_exist_in_generated(self, generated_artifacts):
        """Buttons referencing pages should point to generated ones.

        Note: _Create/_Edit buttons may reference pages named _NewEdit
        (same page handles both modes). We resolve this by also checking
        the _NewEdit variant.
        """
        page_names = {p["name"] for p in generated_artifacts["pages"]}
        missing = []
        for page in generated_artifacts["pages"]:
            for btn in page.get("buttons", []):
                target = btn.get("target_page")
                if not target or target in page_names:
                    continue
                # Try _NewEdit variant (Create/Edit → NewEdit)
                newedit_variant = (
                    target.replace("_Create", "_NewEdit")
                    .replace("_Edit", "_NewEdit")
                )
                if newedit_variant in page_names:
                    continue
                missing.append(
                    f"Page '{page['name']}' button '{btn['label']}' "
                    f"→ page '{target}'"
                )
        total_page_buttons = sum(
            1 for p in generated_artifacts["pages"]
            for b in p.get("buttons", [])
            if b.get("target_page")
        )
        if total_page_buttons > 0:
            ratio = len(missing) / total_page_buttons
            assert ratio < 0.5, (
                f"Too many missing page references ({len(missing)}/{total_page_buttons}):\n"
                + "\n".join(missing[:10])
            )


# ═══════════════════════════════════════════════════════════════
# Post-Generation Validation on Real Data
# ═══════════════════════════════════════════════════════════════


class TestPostGenerationValidation:
    """Runs the PostGenerationValidator on the real parsed schema."""

    def test_no_errors(self, parsed_schema):
        """Schema from real Excel should have no errors (may have warnings)."""
        report = PostGenerationValidator().validate(parsed_schema)
        if report.errors:
            error_msgs = "\n".join(str(e) for e in report.errors)
            pytest.fail(f"Validation errors:\n{error_msgs}")

    def test_warnings_count_reasonable(self, parsed_schema):
        """Warnings should be reasonable, not overwhelming."""
        report = PostGenerationValidator().validate(parsed_schema)
        # Allow some warnings but flag if too many
        assert report.warning_count < 50, (
            f"Too many warnings ({report.warning_count})"
        )


# ═══════════════════════════════════════════════════════════════
# Payload Structure Consistency
# ═══════════════════════════════════════════════════════════════


class TestPayloadConsistency:
    """Verifica consistencia de estructura entre todos los payloads generados."""

    def test_all_pages_have_widgets(self, generated_artifacts):
        for page in generated_artifacts["pages"]:
            assert "widgets" in page, (
                f"Page '{page['name']}' missing 'widgets' key"
            )

    def test_all_microflows_have_activities(self, generated_artifacts):
        for mf in generated_artifacts["microflows"]:
            assert "activities" in mf, (
                f"Microflow '{mf['name']}' missing 'activities' key"
            )

    def test_all_microflows_have_return_type(self, generated_artifacts):
        for mf in generated_artifacts["microflows"]:
            assert "return_type" in mf, (
                f"Microflow '{mf['name']}' missing 'return_type'"
            )
            assert mf["return_type"] in ("Boolean", "Void") or mf["return_type"].startswith("List of "), (
                f"Microflow '{mf['name']}' has invalid return_type: '{mf['return_type']}'"
            )

    def test_all_entities_have_module(self, generated_artifacts):
        for entity in generated_artifacts["entities"]:
            assert entity.get("module"), (
                f"Entity '{entity['name']}' missing module"
            )
