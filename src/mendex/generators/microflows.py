"""Generador de microflows (validación/guardado/eliminación) via Model SDK.

Recibe MicroflowSchema del IntermediateSchema y crea microflows en el .mpr.
Genera la estructura base del microflow según su tipo:
- Validation: parámetro de entrada + actividades de validación por campo
- Save: validación + commit + close page
- Delete: confirmación + delete + close page

Fase 9: Implementación completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.sdk_client import SDKClient, SDKClientError
from mendex.logging.decision_logger import DecisionLogger
from mendex.schema.intermediate import (
    AssociationSchema,
    EntitySchema,
    IntermediateSchema,
    MicroflowSchema,
    MicroflowType,
    PageType,
)

logger = structlog.get_logger(__name__)


# ─── Resultado ───────────────────────────────────────────────


@dataclass
class MicroflowResult:
    """Resultado de la creación de un microflow."""

    name: str
    module: str
    microflow_type: str
    success: bool
    activities_count: int = 0
    error: str | None = None

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"MicroflowResult({status} {self.module}.{self.name} [{self.microflow_type}])"


@dataclass
class MicroflowGenerationResult:
    """Resultado completo de la generación de microflows."""

    microflows: list[MicroflowResult] = field(default_factory=list)
    total_created: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.total_failed == 0

    def summary(self) -> str:
        return (
            f"Microflow Generation: {self.total_created} created, "
            f"{self.total_skipped} skipped, {self.total_failed} failed"
        )


# ─── Generador ───────────────────────────────────────────────


class MicroflowGenerator:
    """Genera microflows en un .mpr via SDK Bridge.

    Cada tipo de microflow genera una estructura diferente:
    - VALIDATION: input parameter → validation activities → end (true/false)
    - SAVE: input parameter → validate → commit → close page
    - DELETE: input parameter → show confirmation → delete → close page
    - CUSTOM: input parameter → (empty body for manual completion)

    Uso:
        generator = MicroflowGenerator(sdk_client=sdk_client)
        result = generator.generate(schema, mpr_path)
    """

    def __init__(
        self,
        sdk_client: SDKClient,
        decision_logger: DecisionLogger | None = None,
        skip_existing: bool = True,
    ) -> None:
        self._sdk = sdk_client
        self._decision_logger = decision_logger
        self._skip_existing = skip_existing

    def generate(
        self,
        schema: IntermediateSchema,
        mpr_path: Path,
        *,
        input_hash: str = "",
    ) -> MicroflowGenerationResult:
        """Genera todos los microflows del schema.

        Also generates:
        - ACT_{Entity}_Calculate for entities with calculated fields
        - ACT_{Entity}_CascadeDelete for associations with cascade_delete=True

        Args:
            schema: IntermediateSchema con microflows a crear.
            mpr_path: Path al .mpr.
            input_hash: Hash del input (para logging).

        Returns:
            MicroflowGenerationResult.
        """
        result = MicroflowGenerationResult()

        entity_map = {e.name: e for e in schema.entities}

        # Collect all microflows to create: explicit + auto-generated
        all_microflows: list[MicroflowSchema] = list(schema.microflows)

        # Auto-generate calculation microflows for entities with calculated fields
        for entity in schema.entities:
            calc_attrs = [a for a in entity.attributes if a.is_calculated]
            if calc_attrs:
                calc_desc = "; ".join(
                    f"{a.name} = {a.calculation_expression or 'TBD'}"
                    for a in calc_attrs
                )
                all_microflows.append(MicroflowSchema(
                    name=f"ACT_{entity.name}_Calculate",
                    microflow_type=MicroflowType.CUSTOM,
                    entity=entity.name,
                    module=entity.module,
                    logic_description=f"Calcular campos derivados: {calc_desc}",
                ))

        # Auto-generate seed data microflows for lookup entities
        for entity in schema.entities:
            if entity.is_lookup and entity.seed_values:
                values_str = ", ".join(entity.seed_values)
                seed_activities: list[dict[str, Any]] = []
                for value in entity.seed_values:
                    seed_activities.append({
                        "type": "RetrieveActivity",
                        "action": "find_by_name",
                        "entity": entity.name,
                        "value": value,
                    })
                    seed_activities.append({
                        "type": "CreateActivity",
                        "action": "create_if_not_exists",
                        "entity": entity.name,
                        "attribute": "Name",
                        "value": value,
                    })
                all_microflows.append(MicroflowSchema(
                    name=f"ASe_Initialize{entity.name}",
                    microflow_type=MicroflowType.CUSTOM,
                    entity=entity.name,
                    module=entity.module,
                    logic_description=(
                        f"After Startup: inicializar tabla maestra {entity.name} "
                        f"con valores [{values_str}]. "
                        f"Para cada valor, si no existe registro con Name=valor, crearlo."
                    ),
                ))

        # Auto-generate DS_OS_ (selectable objects) microflows for lookup entities
        for entity in schema.entities:
            if entity.is_lookup:
                all_microflows.append(MicroflowSchema(
                    name=f"DS_OS_{entity.name}",
                    microflow_type=MicroflowType.DATA_SOURCE,
                    entity=entity.name,
                    module=entity.module,
                    logic_description=(
                        f"Recuperar todos los objetos de {entity.name} "
                        f"para selección en formularios (Selectable Objects)"
                    ),
                    return_entity=entity.name,
                ))

        # Auto-generate SUB_SetSecuencia microflows for sequential entities
        for entity in schema.entities:
            if entity.has_sequential:
                all_microflows.append(MicroflowSchema(
                    name=f"SUB_{entity.name}_SetSecuencia",
                    microflow_type=MicroflowType.SEQUENCE,
                    entity=entity.name,
                    module=entity.module,
                    logic_description=(
                        f"Asignar número secuencial a {entity.name}: "
                        f"max(Secuencia existentes) + 1"
                    ),
                ))

        # Auto-generate DS_Filtros microflows for pages with filter entities
        seen_ds_filtros: set[str] = set()
        for page in schema.pages:
            if page.filter_entity and page.page_type == PageType.OVERVIEW:
                mf_name = f"DS_{page.entity}_Filtros"
                if mf_name not in seen_ds_filtros:
                    seen_ds_filtros.add(mf_name)
                    all_microflows.append(MicroflowSchema(
                        name=mf_name,
                        microflow_type=MicroflowType.DATA_SOURCE,
                        entity=page.filter_entity,
                        module=page.module,
                        logic_description=(
                            f"Recuperar valores distintos de la data actual de "
                            f"{page.entity} para cada filtro dinámico"
                        ),
                        return_entity=page.filter_entity,
                    ))

        # Auto-generate cascade delete microflows
        for assoc in schema.associations:
            if assoc.cascade_delete:
                all_microflows.append(MicroflowSchema(
                    name=f"ACT_{assoc.parent_entity}_CascadeDelete",
                    microflow_type=MicroflowType.DELETE,
                    entity=assoc.parent_entity,
                    module=entity_map[assoc.parent_entity].module
                    if assoc.parent_entity in entity_map
                    else schema.entities[0].module if schema.entities else "Default",
                    logic_description=(
                        f"Eliminar {assoc.parent_entity} con sus "
                        f"{assoc.child_entity} asociados (cascade)"
                    ),
                ))

        if not all_microflows:
            return result

        logger.info(
            "microflow_generation_started",
            microflows=len(all_microflows),
        )

        for mf in all_microflows:
            entity = entity_map.get(mf.entity)
            mf_result = self._create_microflow(mf, entity, mpr_path)
            result.microflows.append(mf_result)

            if mf_result.success and mf_result.error is None:
                result.total_created += 1
            elif mf_result.success and mf_result.error:
                result.total_skipped += 1
            else:
                result.total_failed += 1
                result.errors.append(mf_result.error or "Unknown error")

        if self._decision_logger:
            self._decision_logger.log(
                operation="microflow_generation",
                input_hash=input_hash,
                action_taken="generated" if result.success else "failed",
                warnings=result.errors,
                extra={
                    "total_created": result.total_created,
                    "total_skipped": result.total_skipped,
                    "total_failed": result.total_failed,
                },
            )

        logger.info(
            "microflow_generation_complete",
            created=result.total_created,
            skipped=result.total_skipped,
            failed=result.total_failed,
        )

        return result

    def generate_single(
        self,
        microflow: MicroflowSchema,
        entity: EntitySchema | None,
        mpr_path: Path,
    ) -> MicroflowResult:
        """Genera un solo microflow."""
        return self._create_microflow(microflow, entity, mpr_path)

    def _create_microflow(
        self,
        mf: MicroflowSchema,
        entity: EntitySchema | None,
        mpr_path: Path,
    ) -> MicroflowResult:
        """Crea un microflow via SDK Bridge."""
        if self._skip_existing:
            try:
                if self._sdk.check_artifact_exists(
                    mpr_path, "microflow", mf.module, mf.name
                ):
                    return MicroflowResult(
                        name=mf.name,
                        module=mf.module,
                        microflow_type=mf.microflow_type.value,
                        success=True,
                        error=f"Microflow '{mf.name}' ya existe — omitido",
                    )
            except SDKClientError:
                pass

        mf_data = self._build_microflow_data(mf, entity)

        try:
            self._sdk.create_microflow(mpr_path, mf_data)
            activities_count = len(mf_data.get("activities", []))
            logger.info(
                "microflow_created",
                microflow=mf.name,
                module=mf.module,
                type=mf.microflow_type.value,
                activities=activities_count,
            )
            return MicroflowResult(
                name=mf.name,
                module=mf.module,
                microflow_type=mf.microflow_type.value,
                success=True,
                activities_count=activities_count,
            )
        except SDKClientError as e:
            return MicroflowResult(
                name=mf.name,
                module=mf.module,
                microflow_type=mf.microflow_type.value,
                success=False,
                error=str(e),
            )

    def _build_microflow_data(
        self,
        mf: MicroflowSchema,
        entity: EntitySchema | None,
    ) -> dict[str, Any]:
        """Construye los datos del microflow para el SDK Bridge."""
        data: dict[str, Any] = {
            "name": mf.name,
            "microflow_type": mf.microflow_type.value,
            "entity": mf.entity,
            "module": mf.module,
            "logic_description": mf.logic_description,
            "input_parameter": {
                "name": mf.entity,
                "entity": f"{mf.module}.{mf.entity}",
            },
            "activities": self._generate_activities(mf, entity),
            "return_type": self._determine_return_type(mf),
        }
        return data

    def _generate_activities(
        self,
        mf: MicroflowSchema,
        entity: EntitySchema | None,
    ) -> list[dict[str, Any]]:
        """Genera las actividades del microflow según su tipo."""
        if mf.microflow_type == MicroflowType.VALIDATION:
            return self._validation_activities(mf, entity)
        elif mf.microflow_type == MicroflowType.SAVE:
            return self._save_activities(mf, entity)
        elif mf.microflow_type == MicroflowType.DELETE:
            return self._delete_activities(mf)
        elif mf.microflow_type == MicroflowType.DATA_SOURCE:
            return self._data_source_activities(mf)
        elif mf.microflow_type == MicroflowType.SEQUENCE:
            return self._sequence_activities(mf)
        else:
            # CUSTOM: empty body
            return []

    def _validation_activities(
        self,
        mf: MicroflowSchema,
        entity: EntitySchema | None,
    ) -> list[dict[str, Any]]:
        """Genera actividades de validación por campo requerido."""
        activities: list[dict[str, Any]] = []

        if entity:
            for attr in entity.attributes:
                if attr.required:
                    activities.append({
                        "type": "ValidationActivity",
                        "action": "validate_required",
                        "attribute": attr.name,
                        "entity": mf.entity,
                        "error_message": f"El campo {attr.label} es requerido",
                    })

                for validation in attr.validations:
                    if validation.type.value == "required":
                        continue  # Already handled above
                    activities.append({
                        "type": "ValidationActivity",
                        "action": f"validate_{validation.type.value}",
                        "attribute": attr.name,
                        "entity": mf.entity,
                        "params": validation.params,
                        "error_message": validation.error_message,
                    })

        return activities

    def _save_activities(
        self,
        mf: MicroflowSchema,
        entity: EntitySchema | None,
    ) -> list[dict[str, Any]]:
        """Genera actividades: validate → commit → close page."""
        activities: list[dict[str, Any]] = []

        # 1. Call validation microflow (sub-microflow call)
        activities.append({
            "type": "MicroflowCallActivity",
            "action": "call_validation",
            "microflow": f"{mf.module}.VAL_{mf.entity}_Validate",
            "description": f"Validar {mf.entity}",
        })

        # 2. Commit
        activities.append({
            "type": "CommitActivity",
            "action": "commit",
            "entity": mf.entity,
            "with_events": True,
        })

        # 3. Close page
        activities.append({
            "type": "ClosePageActivity",
            "action": "close_page",
        })

        return activities

    def _delete_activities(self, mf: MicroflowSchema) -> list[dict[str, Any]]:
        """Genera actividades: confirm → delete → close page."""
        return [
            {
                "type": "ShowMessageActivity",
                "action": "confirm_delete",
                "message": f"¿Está seguro de eliminar este {mf.entity}?",
                "message_type": "confirmation",
            },
            {
                "type": "DeleteActivity",
                "action": "delete",
                "entity": mf.entity,
            },
            {
                "type": "ClosePageActivity",
                "action": "close_page",
            },
        ]

    def _data_source_activities(self, mf: MicroflowSchema) -> list[dict[str, Any]]:
        """Genera actividades para microflow DataSource (retrieve all)."""
        return [
            {
                "type": "RetrieveActivity",
                "action": "retrieve_all",
                "entity": mf.entity,
                "source": "database",
                "description": mf.logic_description,
            },
        ]

    def _sequence_activities(self, mf: MicroflowSchema) -> list[dict[str, Any]]:
        """Genera actividades para microflow de numeración secuencial."""
        return [
            {
                "type": "RetrieveActivity",
                "action": "aggregate_max",
                "entity": mf.entity,
                "attribute": "Secuencia",
                "description": "Obtener máximo valor de Secuencia actual",
            },
            {
                "type": "ChangeActivity",
                "action": "set_attribute",
                "entity": mf.entity,
                "attribute": "Secuencia",
                "value": "$MaxSecuencia + 1",
                "description": "Asignar siguiente número secuencial",
            },
        ]

    @staticmethod
    def _determine_return_type(mf: MicroflowSchema) -> str:
        """Determina el tipo de retorno del microflow."""
        if mf.microflow_type == MicroflowType.VALIDATION:
            return "Boolean"
        if mf.microflow_type == MicroflowType.DATA_SOURCE:
            return f"List of {mf.return_entity or mf.entity}"
        return "Void"
