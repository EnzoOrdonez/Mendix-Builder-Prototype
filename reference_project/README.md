# Proyecto de Referencia — COPEINCA

Coloca aquí el archivo `.mpr` del proyecto COPEINCA (Mendix 10.24).

## Instrucciones

1. Copiar el archivo `.mpr` a esta carpeta:
   ```
   reference_project/COPEINCA.mpr
   ```

2. El archivo `.mpr` está en `.gitignore` — **nunca se commitea** (datos sensibles).

3. Para extraer convenciones:
   ```bash
   mendex refresh-conventions --mpr reference_project/COPEINCA.mpr
   ```

4. Las convenciones extraídas se guardan en `conventions/copeinca_conventions.yaml`
   (ese archivo SÍ se commitea).

## Importante

- Este directorio es de **solo lectura** para el agente.
- El agente **nunca modifica** el .mpr de referencia.
- Solo se lee durante `refresh-conventions`, no durante operación normal.
