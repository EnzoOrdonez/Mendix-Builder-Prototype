# Mendix Architecture Best Practices

## Domain Model Design

A well-designed domain model is the foundation of a maintainable Mendix application.

### Rules

- Keep entities focused: each entity should represent one concept
- Avoid God entities with too many attributes (more than 20 is a warning sign)
- Use associations instead of duplicating data across entities
- Define generalizations (inheritance) only when there's a true "is-a" relationship
- Mark entities as non-persistable when they're only needed for UI state

### Severity

This is a WARNING-level best practice. Poor domain model design leads to maintainability issues.

## Microflow Design

Microflows should be small, focused, and reusable.

### Rules

- Keep microflows under 25 activities (actions)
- Extract reusable logic into sub-microflows (SUB_ prefix)
- Use a single responsibility principle: one microflow, one purpose
- Always handle errors with error handlers in critical microflows
- Avoid deeply nested decision splits (more than 3 levels)

### Severity

This is a WARNING-level best practice. Complex microflows are harder to debug and maintain.

### Examples

- Good: `ACT_Order_Save` calls `VAL_Order_Validate` and `SUB_Order_SendNotification`
- Bad: One giant microflow that validates, saves, sends email, and updates related entities

## Page Design

Pages should be clean, focused, and follow consistent layout patterns.

### Rules

- Use layout grids for responsive design
- Keep forms focused: one entity per form (avoid multi-entity forms)
- Use data views for object-level forms
- Use list views or data grids for overview pages
- Place action buttons consistently (top-right or bottom of forms)

## Performance

Design for performance from the beginning.

### Rules

- Use XPath constraints on list views and data grids to limit data retrieval
- Avoid retrieving all objects when only a subset is needed
- Use indexes on attributes that are frequently used in searches
- Limit the depth of nested data views (max 3 levels)
- Use non-persistable entities for temporary calculations
