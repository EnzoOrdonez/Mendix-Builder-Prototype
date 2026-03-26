"""Generador de Domain Model (entidades + atributos) via Model SDK.

Recibe un IntermediateSchema (o DryRunReport confirmado) y crea
las entidades con sus atributos, tipos de dato y reglas de acceso
en el .mpr via el SDK Bridge.

Cada operación se ejecuta dentro de un contexto atómico de rollback:
si cualquier creación falla, se restaura el .mpr al estado previo.

Fase 8: Implementación completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.rollback import RollbackManager, atomic_mpr_operation
from mendex.bridge.sdk_client import SDKClient, SDKClientError
from mendex.logging.decision_logger import DecisionLogger
from mendex.schema.intermediate import (
    AccessRuleSchema,
    AssociationSchema,
    AttributeSchema,
    EntitySchema,
    IntermediateSchema,
    MendixDataType,
)

logger = structlog.get_logger(__name__)


# ─── Resultado de generación ────────────────────────────────


@dataclass
class EntityResult:
    """Resultado de la creación de una entidad."""

    name: str
    module: str
    success: bool
    attributes_created: int = 0
    access_rules_created: int = 0
    error: str | None = None

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"EntityResult({status} {self.module}.{self.name}, attrs={self.attributes_created})"


@dataclass
class AssociationResult:
    """Resultado de la creación de una asociación."""

    name: str
    parent_entity: str
    child_entity: str
    success: bool
    error: str | None = None

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"AssociationResult({status} {self.name}: {self.parent_entity}→{self.child_entity})"


@dataclass
class GenerationResult:
    """Resultado completo de la generación del domain model."""

    entities: list[EntityResult] = field(default_factory=list)
    associations: list[AssociationResult] = field(default_factory=list)
    total_created: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    associations_created: int = 0
    associations_failed: int = 0
    errors: list[str] = field(default_factory=list)
    rollback_triggered: bool = False

    @property
    def success(self) -> bool:
        return self.total_failed == 0 and self.associations_failed == 0 and not self.rollback_triggered

    def summary(self) -> str:
        lines = [
            f"Domain Model Generation: "
            f"{self.total_created} created, "
            f"{self.total_skipped} skipped, "
            f"{self.total_failed} failed",
        ]
        if self.associations_created or self.associations_failed:
            lines.append(
                f"Associations: {self.associations_created} created, "
                f"{self.associations_failed} failed"
            )
        if self.rollback_triggered:
            lines.append("⚠ Rollback triggered — .mpr restored to previous state")
        for err in self.errors:
            lines.append(f"  ✗ {err}")
        return "\n".join(lines)


# ─── Generador ───────────────────────────────────────────────


class DomainModelGenerator:
    """Genera entidades del domain model en un .mpr via SDK Bridge.

    Uso:
        generator = DomainModelGenerator(
            sdk_client=sdk_client,
            rollback_manager=rollback_manager,
        )
        result = generator.generate(
            schema=intermediate_schema,
            mpr_path=Path("proyecto.mpr"),
        )

    Con dry-run report (solo entidades aprobadas):
        result = generator.generate_approved(
            schema=intermediate_schema,
            mpr_path=mpr_path,
            approved_entities=["OrdenCompra", "LineaDetalle"],
        )
    """

    def __init__(
        self,
        sdk_client: SDKClient,
        rollback_manager: RollbackManager | None = None,
        decision_logger: DecisionLogger | None = None,
        skip_existing: bool = True,
    ) -> None:
        """Inicializa el generador.

        Args:
            sdk_client: Cliente del SDK bridge.
            rollback_manager: Manager de backup/restore (opcional).
            decision_logger: Logger de decisiones (opcional).
            skip_existing: Si True, omite entidades que ya existen.
        """
        self._sdk = sdk_client
        self._rollback = rollback_manager
        self._decision_logger = decision_logger
        self._skip_existing = skip_existing

    def generate(
        self,
        schema: IntermediateSchema,
        mpr_path: Path,
        *,
        input_hash: str = "",
    ) -> GenerationResult:
        """Genera todas las entidades y asociaciones del schema en el .mpr.

        Args:
            schema: IntermediateSchema con las entidades a crear.
            mpr_path: Path al archivo .mpr destino.
            input_hash: Hash del input original (para logging).

        Returns:
            GenerationResult con el resumen de la operación.
        """
        return self._execute_generation(
            entities=schema.entities,
            associations=schema.associations,
            mpr_path=mpr_path,
            input_hash=input_hash,
        )

    def generate_approved(
        self,
        schema: IntermediateSchema,
        mpr_path: Path,
        approved_entities: list[str],
        *,
        input_hash: str = "",
    ) -> GenerationResult:
        """Genera solo las entidades aprobadas del schema.

        Args:
            schema: IntermediateSchema con las entidades.
            mpr_path: Path al .mpr destino.
            approved_entities: Lista de nombres de entidades aprobadas.
            input_hash: Hash del input.

        Returns:
            GenerationResult.
        """
        approved_set = set(approved_entities)
        entities = [e for e in schema.entities if e.name in approved_set]
        return self._execute_generation(
            entities=entities,
            mpr_path=mpr_path,
            input_hash=input_hash,
        )

    def generate_single(
        self,
        entity: EntitySchema,
        mpr_path: Path,
        *,
        input_hash: str = "",
    ) -> EntityResult:
        """Genera una sola entidad en el .mpr.

        Args:
            entity: EntitySchema a crear.
            mpr_path: Path al .mpr.
            input_hash: Hash del input.

        Returns:
            EntityResult con el resultado de la creación.
        """
        result = self._execute_generation(
            entities=[entity],
            mpr_path=mpr_path,
            input_hash=input_hash,
        )
        if result.entities:
            return result.entities[0]
        return EntityResult(
            name=entity.name,
            module=entity.module,
            success=False,
            error="No result returned",
        )

    def _execute_generation(
        self,
        entities: list[EntitySchema],
        mpr_path: Path,
        input_hash: str,
        associations: list[AssociationSchema] | None = None,
    ) -> GenerationResult:
        """Ejecuta la generación con rollback atómico."""
        result = GenerationResult()

        if not entities:
            logger.info("domain_model_generation_skipped", reason="no entities")
            return result

        logger.info(
            "domain_model_generation_started",
            entities=len(entities),
            associations=len(associations) if associations else 0,
            mpr_path=str(mpr_path),
        )

        entity_map = {e.name: e for e in entities}

        # Si hay rollback manager, usar operación atómica
        if self._rollback:
            try:
                with atomic_mpr_operation(self._rollback, mpr_path):
                    self._create_entities(entities, mpr_path, result)
                    if associations:
                        self._create_associations(associations, mpr_path, result, entity_map)
            except Exception as e:
                result.rollback_triggered = True
                result.errors.append(f"Rollback triggered: {e}")
                logger.error(
                    "domain_model_rollback",
                    error=str(e),
                    entities_attempted=len(entities),
                )
        else:
            self._create_entities(entities, mpr_path, result)
            if associations:
                self._create_associations(associations, mpr_path, result, entity_map)

        # Log
        if self._decision_logger:
            self._decision_logger.log(
                operation="domain_model_generation",
                input_hash=input_hash,
                action_taken="generated" if result.success else "failed",
                warnings=result.errors,
                extra={
                    "total_created": result.total_created,
                    "total_skipped": result.total_skipped,
                    "total_failed": result.total_failed,
                    "associations_created": result.associations_created,
                    "associations_failed": result.associations_failed,
                    "rollback": result.rollback_triggered,
                },
            )

        logger.info(
            "domain_model_generation_complete",
            created=result.total_created,
            skipped=result.total_skipped,
            failed=result.total_failed,
            associations_created=result.associations_created,
            rollback=result.rollback_triggered,
        )

        return result

    def _create_entities(
        self,
        entities: list[EntitySchema],
        mpr_path: Path,
        result: GenerationResult,
    ) -> None:
        """Crea las entidades una por una via SDK Bridge."""
        for entity in entities:
            entity_result = self._create_single_entity(entity, mpr_path)
            result.entities.append(entity_result)

            if entity_result.error and "ya existe" in entity_result.error:
                result.total_skipped += 1
            elif entity_result.success:
                result.total_created += 1
            else:
                result.total_failed += 1

    def _create_single_entity(
        self, entity: EntitySchema, mpr_path: Path
    ) -> EntityResult:
        """Crea una sola entidad via SDK Bridge."""
        # Check if exists
        if self._skip_existing:
            try:
                exists = self._sdk.check_artifact_exists(
                    mpr_path, "entity", entity.module, entity.name
                )
                if exists:
                    logger.debug(
                        "entity_skipped_exists",
                        entity=entity.name,
                        module=entity.module,
                    )
                    return EntityResult(
                        name=entity.name,
                        module=entity.module,
                        success=True,
                        error=f"Entity '{entity.name}' ya existe — omitida",
                    )
            except SDKClientError as e:
                logger.warning(
                    "entity_exists_check_failed",
                    entity=entity.name,
                    error=str(e),
                )

        # Build entity data for SDK
        entity_data = self._build_entity_data(entity)

        try:
            sdk_result = self._sdk.create_entity(mpr_path, entity_data)
            logger.info(
                "entity_created",
                entity=entity.name,
                module=entity.module,
                attributes=len(entity.attributes),
                sdk_result=sdk_result.get("status", "unknown"),
            )
            return EntityResult(
                name=entity.name,
                module=entity.module,
                success=True,
                attributes_created=len(entity.attributes),
                access_rules_created=len(entity.access_rules),
            )
        except SDKClientError as e:
            logger.error(
                "entity_creation_failed",
                entity=entity.name,
                module=entity.module,
                error=str(e),
            )
            return EntityResult(
                name=entity.name,
                module=entity.module,
                success=False,
                error=str(e),
            )

    @staticmethod
    def _build_entity_data(entity: EntitySchema) -> dict[str, Any]:
        """Convierte EntitySchema a dict para el SDK Bridge."""
        data: dict[str, Any] = {
            "name": entity.name,
            "module": entity.module,
            "is_persistable": entity.is_persistable,
            "attributes": [
                DomainModelGenerator._build_attribute_data(attr)
                for attr in entity.attributes
            ],
            "access_rules": [
                DomainModelGenerator._build_access_rule_data(rule)
                for rule in entity.access_rules
            ],
        }
        if entity.generalization:
            data["generalization"] = entity.generalization
        if entity.is_lookup:
            data["is_lookup"] = True
        if entity.seed_values:
            data["seed_values"] = entity.seed_values
        return data

    @staticmethod
    def _build_attribute_data(attr: AttributeSchema) -> dict[str, Any]:
        """Convierte AttributeSchema a dict para el SDK Bridge."""
        data: dict[str, Any] = {
            "name": attr.name,
            "mendix_type": attr.mendix_type.value,
            "label": attr.label,
            "required": attr.required,
        }

        if attr.default_value is not None:
            data["default_value"] = attr.default_value

        if attr.enum_values:
            data["enum_values"] = attr.enum_values

        if attr.validations:
            data["validations"] = [
                {
                    "type": v.type.value,
                    "params": v.params,
                    "error_message": v.error_message,
                }
                for v in attr.validations
            ]

        return data

    @staticmethod
    def _build_access_rule_data(rule: AccessRuleSchema) -> dict[str, Any]:
        """Convierte AccessRuleSchema a dict para el SDK Bridge."""
        return {
            "role": rule.role,
            "can_create": rule.can_create,
            "can_read": rule.can_read,
            "can_write": rule.can_write,
            "can_delete": rule.can_delete,
        }

    def _create_associations(
        self,
        associations: list[AssociationSchema],
        mpr_path: Path,
        result: GenerationResult,
        entity_map: dict[str, EntitySchema] | None = None,
    ) -> None:
        """Crea las asociaciones entre entidades via SDK Bridge."""
        for assoc in associations:
            assoc_data = self._build_association_data(assoc, entity_map)
            try:
                self._sdk.create_association(mpr_path, assoc_data)
                result.associations.append(AssociationResult(
                    name=assoc.name,
                    parent_entity=assoc.parent_entity,
                    child_entity=assoc.child_entity,
                    success=True,
                ))
                result.associations_created += 1
                logger.info(
                    "association_created",
                    name=assoc.name,
                    parent=assoc.parent_entity,
                    child=assoc.child_entity,
                    type=assoc.association_type.value,
                )
            except SDKClientError as e:
                result.associations.append(AssociationResult(
                    name=assoc.name,
                    parent_entity=assoc.parent_entity,
                    child_entity=assoc.child_entity,
                    success=False,
                    error=str(e),
                ))
                result.associations_failed += 1
                result.errors.append(
                    f"Association '{assoc.name}' failed: {e}"
                )

    def _build_association_data(
        self,
        assoc: AssociationSchema,
        entity_map: dict[str, EntitySchema] | None = None,
    ) -> dict[str, Any]:
        """Convierte AssociationSchema a dict para el SDK Bridge."""
        # Resolve module from parent entity
        module = ""
        if entity_map and assoc.parent_entity in entity_map:
            module = entity_map[assoc.parent_entity].module

        data: dict[str, Any] = {
            "name": assoc.name,
            "parent_entity": assoc.parent_entity,
            "child_entity": assoc.child_entity,
            "association_type": assoc.association_type.value,
            "module": module,
            "owner": assoc.owner,
            "cascade_delete": assoc.cascade_delete,
        }
        if assoc.is_lookup:
            data["is_lookup"] = True
        return data
