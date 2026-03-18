# Convenciones de Naming en Figma para MendixFormAgent

## Resumen

Para que el extractor de Figma pueda convertir tu diseño en artefactos Mendix,
los layers y frames deben seguir estas convenciones de nombres.

## Convenciones Obligatorias

### Frame principal del formulario
```
form_{NombreEntidad}
```
Ejemplo: `form_OrdenCompra`, `form_RegistroPesca`

### Campos de input
```
input_{NombreCampo}_{tipo}
```
Tipos soportados: `text`, `number`, `decimal`, `date`, `bool`, `enum`, `textarea`

Ejemplo: `input_Nombre_text`, `input_FechaNacimiento_date`, `input_MontoTotal_decimal`

### Labels
```
label_{NombreCampo}
```
Ejemplo: `label_Nombre`, `label_FechaNacimiento`

### Indicador de campo requerido
```
required_{NombreCampo}
```
O un nodo TEXT con contenido `*` junto al label.

### Botones
```
btn_{Accion}
```
Ejemplo: `btn_Submit`, `btn_Cancel`, `btn_Delete`

### Grupos / Secciones
```
group_{NombreSeccion}
```
Ejemplo: `group_DatosPersonales`, `group_DireccionEnvio`

## Estructura jerárquica esperada

```
form_OrdenCompra           ← Frame principal
├── group_DatosGenerales   ← Sección (opcional)
│   ├── label_Numero
│   ├── input_Numero_number
│   ├── required_Numero
│   ├── label_Fecha
│   └── input_Fecha_date
├── group_Montos
│   ├── label_MontoTotal
│   └── input_MontoTotal_decimal
├── btn_Submit
└── btn_Cancel
```

## Formularios anidados (relación 1-N)

Si un frame `form_*` contiene otro frame `form_*`, se interpreta como una relación
uno-a-muchos entre las entidades.

```
form_OrdenCompra
├── ...campos...
└── form_LineaDetalle     ← Entidad hija (1-N)
    ├── label_Producto
    ├── input_Producto_text
    └── input_Cantidad_number
```

## Errores comunes

| Error | Solución |
|---|---|
| Frame sin prefijo `form_` | El extractor no lo reconoce como formulario |
| Input sin sufijo de tipo | Se asume `text` con warning |
| Label sin input correspondiente | Warning: label huérfano ignorado |
| Tipo no reconocido (ej: `input_X_file`) | Warning + default a `text` |
