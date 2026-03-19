# Mendix Security Best Practices

## Access Rules

Every persistable entity MUST have explicit access rules defined. Without access rules, entities are inaccessible by default (deny-by-default).

### Rules

- Define access rules for EVERY persistable entity
- Follow the principle of least privilege: grant only the minimum permissions necessary
- Use deny-by-default: start with no access and explicitly grant what's needed
- Review access rules regularly as roles and requirements evolve
- Never grant full access to all roles as a shortcut

### Severity

This is a CRITICAL best practice. Missing access rules can lead to security vulnerabilities or runtime errors.

### Examples

- Good: Entity `Order` has explicit rules for `Administrator` (CRUD), `User` (CR), `ReadOnly` (R)
- Bad: Entity `Order` has no access rules defined
- Bad: Entity `Order` grants full CRUD to all roles

## Module Security

Each module should have its own security configuration that aligns with the application's role structure.

### Rules

- Define module roles that map to project-level roles
- Keep module security aligned with the overall security model
- Document which roles have access to which modules

## Password Security

Sensitive data should use HashedString type for passwords and never store plain text.

### Rules

- Always use HashedString for password fields
- Never log or display password values
- Implement password complexity requirements via validation microflows

## Data Validation

All user input must be validated before processing.

### Rules

- Implement validation microflows for every form
- Validate required fields, data types, and business rules
- Provide clear, localized error messages
- Validate on the server side (microflows), not just client side

### Examples

- Good: `VAL_Order_Validate` microflow checks all required fields and business rules
- Bad: Relying only on widget-level required validation
