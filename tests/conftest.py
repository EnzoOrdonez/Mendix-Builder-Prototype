"""Fixtures compartidos para tests del agente MendixFormAgent."""

from __future__ import annotations

from pathlib import Path

import pytest

from mendex.schema.intermediate import (
    AttributeSchema,
    EntitySchema,
    InputSource,
    IntermediateSchema,
    MendixDataType,
)


@pytest.fixture
def fixtures_dir() -> Path:
    """Path al directorio de fixtures."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_entity() -> EntitySchema:
    """Entidad de ejemplo para tests."""
    return EntitySchema(
        name="OrdenCompra",
        module="Operaciones",
        attributes=[
            AttributeSchema(
                name="Numero",
                mendix_type=MendixDataType.AUTONUMBER,
                label="Número de Orden",
            ),
            AttributeSchema(
                name="FechaCreacion",
                mendix_type=MendixDataType.DATETIME,
                label="Fecha de Creación",
                required=True,
            ),
            AttributeSchema(
                name="MontoTotal",
                mendix_type=MendixDataType.DECIMAL,
                label="Monto Total",
                required=True,
            ),
            AttributeSchema(
                name="Descripcion",
                mendix_type=MendixDataType.STRING,
                label="Descripción",
            ),
            AttributeSchema(
                name="Activo",
                mendix_type=MendixDataType.BOOLEAN,
                label="Activo",
            ),
        ],
    )


@pytest.fixture
def sample_schema(sample_entity: EntitySchema) -> IntermediateSchema:
    """IntermediateSchema de ejemplo para tests."""
    return IntermediateSchema(
        source=InputSource.EXCEL,
        source_file="fixtures/sample_form.xlsx",
        entities=[sample_entity],
    )
