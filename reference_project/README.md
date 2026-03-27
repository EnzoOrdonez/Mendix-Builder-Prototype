# Proyecto de Referencia

Coloca aqui el archivo `.mpr` de tu proyecto Mendix de referencia (Mendix 10.24).

## Instrucciones

1. Copiar el archivo `.mpr` a esta carpeta:
   ```
   reference_project/MiProyecto.mpr
   ```

2. El archivo `.mpr` está en `.gitignore` — **nunca se commitea** (datos sensibles).

3. Para extraer convenciones:
   ```bash
   mendex refresh-conventions --mpr reference_project/MiProyecto.mpr
   ```

4. Las convenciones extraídas se guardan en `conventions/project_conventions.yaml`
   (ese archivo SÍ se commitea).

## Importante

- Este directorio es de **solo lectura** para el agente.
- El agente **nunca modifica** el .mpr de referencia.
