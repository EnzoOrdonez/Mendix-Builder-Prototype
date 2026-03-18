# Plan de Migración a Mendix 11

## Resumen

La arquitectura está diseñada para migrar de Mendix 10.24 LTS a Mendix 11.12 MTS
(estimado junio 2026) con cambios mínimos.

## Abstracciones preparadas

| Abstracción | Implementación actual | Implementación futura (Mendix 11) |
|---|---|---|
| `LLMProvider` | `ClaudeProvider` (API directa) | `MendixAIGatewayProvider` |
| `SDKClient` | `SubprocessSDKClient` (Node.js) | `AgentsKitClient` |
| `KnowledgeProvider` | `ChromaDBProvider` (local) | `AgentCommonsProvider` |

## Qué cambia

- El Model SDK externo se reemplaza por Agents Kit + MCP Server nativos
- El servidor FastAPI se convierte en MCP Server registrado en Studio Pro
- La knowledge base local puede migrarse a Agent Commons

## Qué NO cambia

- Lógica de negocio del agente
- IntermediateSchema
- Parser Excel y extractor Figma
- Sistema de dry-run y rollback
- Logging y caché
