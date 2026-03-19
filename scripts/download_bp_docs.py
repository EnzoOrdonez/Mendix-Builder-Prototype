"""Descarga documentación oficial de buenas prácticas de Mendix.

Guarda los documentos como archivos Markdown en knowledge_base/mendix_bp_official/
para ser indexados en el vector store (ChromaDB).

Uso:
    python scripts/download_bp_docs.py

Nota: Algunas páginas de Mendix pueden requerir procesamiento manual
del HTML. Este script intenta hacer la conversión automáticamente,
pero se recomienda revisar los archivos generados.
"""

from __future__ import annotations

import sys
from pathlib import Path

# URLs de documentación oficial de Mendix
BP_SOURCES = [
    {
        "url": "https://docs.mendix.com/refguide/dev-best-practices/",
        "filename": "development_best_practices.md",
        "description": "Development Best Practices generales",
    },
    {
        "url": "https://docs.mendix.com/refguide/best-practice-recommender/",
        "filename": "best_practice_recommender.md",
        "description": "Reglas del Best Practice Recommender",
    },
    {
        "url": "https://docs.mendix.com/howto/security/best-practices-security/",
        "filename": "security_howto.md",
        "description": "How-to de seguridad",
    },
]

OUTPUT_DIR = Path("knowledge_base/mendix_bp_official")


def download_docs() -> None:
    """Descarga documentos de BP oficiales de Mendix."""
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx no instalado. Ejecuta: pip install httpx")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for source in BP_SOURCES:
        url = source["url"]
        filename = source["filename"]
        output_path = OUTPUT_DIR / filename

        print(f"Descargando: {source['description']}")
        print(f"  URL: {url}")

        try:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()

            # Extraer contenido principal (simplificado)
            # En producción, usar beautifulsoup4 o similar para limpiar HTML
            content = response.text

            # Intentar extraer solo el contenido del artículo
            md_content = _html_to_simple_markdown(content, url)

            output_path.write_text(md_content, encoding="utf-8")
            print(f"  → Guardado: {output_path} ({len(md_content)} chars)")

        except httpx.HTTPError as e:
            print(f"  ERROR descargando {url}: {e}")
            print(f"  Puedes descargar manualmente y guardar en {output_path}")

    print("\n✓ Descarga completada.")
    print(f"Archivos en: {OUTPUT_DIR}")
    print("\nNota: Revisa los archivos generados y ajusta el Markdown si es necesario.")
    print("Los archivos incluidos en el repo (naming_conventions.md, etc.) ya están listos para usar.")


def _html_to_simple_markdown(html: str, source_url: str) -> str:
    """Conversión simplificada de HTML a Markdown.

    Para una conversión más robusta, instalar beautifulsoup4 y html2text.
    """
    import re

    # Intentar usar html2text si está disponible
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 100
        md = h.handle(html)
        return f"<!-- Source: {source_url} -->\n\n{md}"
    except ImportError:
        pass

    # Fallback: extraer texto básico del HTML
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return (
        f"<!-- Source: {source_url} -->\n"
        f"<!-- Note: Install html2text for better Markdown conversion -->\n\n"
        f"{text[:5000]}"  # Limitar a 5000 chars en modo fallback
    )


if __name__ == "__main__":
    download_docs()
