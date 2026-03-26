# Guia de Pruebas — MendixFormAgent

## Tests Automatizados

### Correr todos los tests

```bash
pytest tests/ -q
```

Resultado esperado: **773+ tests passed**

### Por categoria

```bash
# Solo unitarios (rapidos, sin dependencias externas)
pytest tests/unit/ -q

# Solo integracion (usan MockSDKClient y fixtures)
pytest tests/integration/ -q

# Un archivo especifico
pytest tests/unit/test_validators.py -v

# Con cobertura
pytest tests/ --cov=src/mendex --cov-report=html
```

### Estructura de tests

```
tests/
├── unit/
│   ├── test_excel_parser.py       # Parser Excel v1 (formato basico)
│   ├── test_excel_parser_v2.py    # Parser Excel v2 (9 patrones UI)
│   ├── test_generators.py         # Generadores domain model/pages/microflows
│   ├── test_validators.py         # Validadores post-generacion y convenciones
│   └── test_mpr_reader.py         # Lector directo de .mpr
├── integration/
│   ├── test_pipeline_integration.py    # Pipeline completo parse→generate
│   ├── test_payload_structure.py       # Contrato Python→TypeScript
│   ├── test_e2e_excel_to_artifacts.py  # Round-trip Excel→artifacts→validacion
│   └── test_mpr_reader_real.py         # Lectura de .mpr real (skip si no hay)
└── conftest.py
```

### Que cubre cada grupo

| Grupo | Tests | Que verifica |
|-------|-------|--------------|
| `test_excel_parser` | ~90 | Parsing de columnas, tipos, validaciones, secciones |
| `test_excel_parser_v2` | ~35 | 9 patrones UI: lookups, secuencial, filtros, config, botones, search, CV, master-detail, popups |
| `test_generators` | ~80 | Generacion de entidades, paginas, microflows con MockSDKClient |
| `test_validators` | ~29 | Cross-references, orphans, naming conventions, PascalCase |
| `test_payload_structure` | ~21 | Estructura de payloads entity/page/microflow/association |
| `test_e2e_excel_to_artifacts` | ~17 | Round-trip completo con fixtures/simulacros_sso.xlsx |
| Otros | ~500+ | Pipeline, dry-run, rollback, auditor, cache, CLI |

---

## Pruebas Reales con Mendix Studio Pro

### Prerequisitos

| Requisito | Version | Donde obtener |
|-----------|---------|---------------|
| Mendix Studio Pro | 10.24.16 LTS | [mendix.com/studio-pro](https://mendix.com) |
| MENDIX_TOKEN | — | [warden.mendix.com](https://warden.mendix.com) → API Keys → Create |
| MENDIX_APP_ID | — | Developer Portal → Tu App → Settings → General |
| Node.js | >= 18 | [nodejs.org](https://nodejs.org) |
| Python | >= 3.11 | [python.org](https://python.org) |

### Paso a paso

#### 1. Crear proyecto de prueba

1. Abrir Mendix Studio Pro
2. File → New App → Blank Web App
3. Nombre: `MendexTest` (o el que prefieras)
4. Crear un modulo nuevo: click derecho en Project → Add Module → `Operaciones`
5. Publicar: Version Control → Commit (Ctrl+Shift+K) y luego Upload to Team Server

#### 2. Obtener credenciales

1. **MENDIX_TOKEN**: Ir a [warden.mendix.com](https://warden.mendix.com) → API Keys → Create Personal Access Token
   - Scopes necesarios: `mx:modelrepository:repo:write`
2. **MENDIX_APP_ID**: Developer Portal → Tu app → Settings → General → App ID (UUID)

#### 3. Configurar entorno

```bash
# Copiar variables de entorno
cp .env.example .env

# Editar .env con tus credenciales:
# MENDIX_TOKEN=tu-token-aqui
# MENDIX_APP_ID=tu-app-id-aqui

# Compilar el bridge TypeScript
cd mendix_sdk && npm install && npm run build && cd ..

# Verificar instalacion
python -m mendex --help
```

#### 4. Generar plantilla Excel

```bash
# Crear plantilla con 2 entidades pre-formateadas
mendex init-excel --module Operaciones --entities 2 --output mi_proyecto.xlsx
```

Esto genera un `.xlsx` con:
- Headers de 15 columnas con dropdowns de validacion
- Hoja `_Relaciones` para asociaciones
- Hoja `_Seguridad` para reglas de acceso
- Filas de ejemplo con una entidad `OrdenCompra`

#### 5. Llenar la plantilla

Abrir `mi_proyecto.xlsx` en Excel y llenar las hojas:

**Hoja de entidad** (ej: `OrdenCompra`):
| NombreCampo | TipoDato | Requerido | Etiqueta | Pagina | Widget |
|---|---|---|---|---|---|
| Numero | AutoNumero | Si | Numero | Todos | |
| Fecha | FechaHora | Si | Fecha | Todos | DatePicker |
| Descripcion | Texto | Si | Descripcion | Todos | TextArea |
| MontoTotal | Decimal | No | Monto Total | Todos | |
| Activo | Booleano | No | Activo | SoloOverview | CheckBox |

**Hoja `_Relaciones`** (si aplica):
| EntidadPadre | EntidadHija | TipoRelacion | CascadeDelete | EsLookup |
|---|---|---|---|---|
| OrdenCompra | LineaDetalle | 1-* | Si | No |

**Hoja `_Seguridad`**:
| Entidad | Rol | PuedeCrear | PuedeLeer | PuedeEscribir | PuedeEliminar |
|---|---|---|---|---|---|
| OrdenCompra | Administrator | Si | Si | Si | Si |
| OrdenCompra | User | Si | Si | Si | No |

#### 6. Validar schema

```bash
# Validar cross-references y naming conventions
mendex validate --input mi_proyecto.xlsx --conventions --module Operaciones
```

Resultado esperado:
```
Validacion OK (X warnings)
```

Si hay errores, corregir el Excel segun las indicaciones.

#### 7. Generar artefactos (dry-run)

```bash
mendex generate --input mi_proyecto.xlsx --mpr "C:\Users\tu\Documents\Mendix\MendexTest\MendexTest.mpr" --module Operaciones
```

Esto muestra un reporte de dry-run:
```
Schema: 2 entidades, 4 paginas, 8 microflows, 1 asociaciones

=== MendixFormAgent — Dry-Run Report ===
Artefactos a generar: 2 entidades, 4 paginas, 8 microflows
...
¿Ejecutar generacion de N artefactos? [y/N]:
```

Confirmar con `y`.

#### 8. Verificar en Studio Pro

1. Abrir el `.mpr` en Studio Pro (File → Open)
2. Studio Pro descargara los cambios del Team Server

**Verificar Domain Model** (doble-click en modulo Operaciones):
- [ ] Entidades creadas con atributos correctos
- [ ] Tipos de dato correctos (Integer, String, DateTime, etc.)
- [ ] Asociaciones visibles entre entidades
- [ ] Reglas de acceso configuradas

**Verificar Paginas** (expandir modulo → Pages):
- [ ] Pagina Overview con DataGrid y columnas
- [ ] Pagina NewEdit con DataView y widgets de input
- [ ] Botones "Guardar", "Cancelar" en paginas de formulario
- [ ] Botones "Nuevo", "Editar", "Eliminar" en overview

**Verificar Microflows** (expandir modulo → Microflows):
- [ ] VAL_{Entity}_Validate con actividades de validacion
- [ ] ACT_{Entity}_Save con Validate → Commit → Close Page
- [ ] ACT_{Entity}_Delete con Confirm → Delete → Close Page
- [ ] DS_OS_{Lookup} para tablas maestras (si aplica)

---

## Troubleshooting

### Error: "openSession failed"
- **Causa**: `MENDIX_TOKEN` invalido o expirado
- **Solucion**: Regenerar token en [warden.mendix.com](https://warden.mendix.com)

### Error: "Module 'X' not found in project"
- **Causa**: El modulo no existe en el .mpr
- **Solucion**: Crear el modulo en Studio Pro primero, publicar, y luego correr mendex

### Error: "Script Node.js no encontrado"
- **Causa**: Bridge no compilado
- **Solucion**: `cd mendix_sdk && npm run build && cd ..`

### Status "already_exists"
- **No es error**: El artefacto ya existe en el .mpr y se omite (skip)
- **Para sobrescribir**: `--on-conflict=overwrite`

### Paginas sin widgets / Microflows sin actividades
- **Causa posible**: El Excel no tiene columnas suficientes
- **Diagnostico**: Correr `mendex validate --input archivo.xlsx` para ver warnings
- **Verificar**: Que las columnas TipoDato, NombreCampo, Pagina esten correctas

### El proceso se cuelga
- **Causa**: El bridge Node.js no responde (ej: token invalido, red caida)
- **Solucion**: Ctrl+C, verificar `.env`, verificar conexion a internet
