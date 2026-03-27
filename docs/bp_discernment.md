# Sistema de Discernimiento de Buenas Prácticas

## Resumen

El agente evalúa cada artefacto generado contra las buenas prácticas oficiales de Mendix
y las convenciones del proyecto de referencia, emitiendo un veredicto para cada patrón.

## Jerarquía de fuentes

1. **BP oficiales de Mendix** (ChromaDB RAG) — siempre tienen prioridad
2. **project_conventions.yaml** — se aplican solo si no contradicen las BP oficiales
3. Si hay conflicto → se aplica la BP oficial y se notifica al usuario

## Veredictos

| Veredicto | Significado | Acción |
|---|---|---|
| **CONFORME** | Cumple las BP oficiales | Proceder |
| **NO_CONFORME** | Viola una BP oficial | Warning (o abort en `--strict`) |
| **SIN_DATOS** | No hay BP aplicable | Proceder con warning |

## Pipeline de evaluación

1. Se recibe la descripción del patrón a evaluar
2. Se buscan los top-5 chunks más relevantes en ChromaDB
3. Se construye un prompt con los chunks + convenciones + patrón
4. Se envía a Claude API (o se lee del caché)
5. Se parsea la respuesta estructurada → BPVerdict

## Modo --strict

Cuando se usa `--strict`, cualquier veredicto `NO_CONFORME` aborta la ejecución.
Útil para equipos que requieren 100% de conformidad con BP oficiales.
