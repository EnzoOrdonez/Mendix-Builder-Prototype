# Mendix Best Practices — Documentación Oficial

Esta carpeta contiene los documentos de buenas prácticas oficiales de Mendix,
descargados como archivos Markdown para ser indexados en el vector store (ChromaDB).

## Cómo poblar esta carpeta

Ejecutar el script de descarga:

```bash
python scripts/download_bp_docs.py
```

Este script descarga las siguientes fuentes:
- [Development Best Practices](https://docs.mendix.com/refguide/dev-best-practices/)
- [Best Practice Recommender Rules](https://docs.mendix.com/refguide/best-practice-recommender/)
- [Naming Conventions](https://docs.mendix.com/refguide/dev-best-practices/#naming-conventions)
- [Security Best Practices](https://docs.mendix.com/howto/security/)

## Formato esperado

Cada archivo `.md` en esta carpeta se chunkeiza por secciones (H2/H3) y se indexa
en ChromaDB con metadata de categoría y severidad.

## Notas

- Los archivos se descargan una vez y se versionan en el repo.
- Para actualizar, re-ejecutar el script.
- La carpeta `chroma_db/` (vector store generado) está en `.gitignore`.
