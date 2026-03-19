# Mendix Naming Conventions — Best Practices

## Entity Naming

Entities should be named using PascalCase (UpperCamelCase). Each entity name should be a singular noun that clearly describes what the entity represents.

### Rules

- Use PascalCase for entity names (e.g., `OrderLine`, `CustomerAddress`)
- Use singular nouns, not plurals (e.g., `Order` not `Orders`)
- Avoid abbreviations unless universally understood (e.g., `URL` is acceptable)
- Do not prefix entity names with the module name
- Use descriptive names that convey the entity's purpose

### Examples

- Good: `SalesOrder`, `CustomerContact`, `InvoiceLine`
- Bad: `tbl_sales_order`, `SO`, `Orders`, `MyModule.SalesOrder`

## Attribute Naming

Attributes should also use PascalCase and clearly describe the data they hold.

### Rules

- Use PascalCase for attribute names
- Boolean attributes should start with `Is`, `Has`, or `Can` (e.g., `IsActive`, `HasDiscount`)
- Date attributes should indicate what the date represents (e.g., `OrderDate`, `CreatedAt`)
- Avoid generic names like `Value`, `Name`, `Status` without context
- Use the full word, not abbreviations (e.g., `Description` not `Desc`)

### Examples

- Good: `TotalAmount`, `IsApproved`, `OrderDate`, `CustomerName`
- Bad: `amt`, `flag`, `dt`, `val1`

## Microflow Naming

Microflows should follow a consistent naming pattern that indicates their purpose.

### Rules

- Prefix microflows with an action indicator:
  - `ACT_` for actions triggered by user interaction
  - `VAL_` for validation microflows
  - `SUB_` for sub-microflows called by other microflows
  - `DS_` for data source microflows
  - `TA_` for scheduled/timer actions
- Follow the prefix with the entity name and a qualifier
- Pattern: `{Prefix}_{EntityName}_{Action}`

### Examples

- Good: `ACT_Order_Save`, `VAL_Customer_ValidateEmail`, `SUB_Invoice_CalculateTotal`
- Bad: `SaveOrder`, `Microflow1`, `DoStuff`

## Page Naming

Pages should indicate the entity they relate to and their purpose.

### Rules

- Pattern: `{EntityName}_{PageType}`
- Common page types: `Overview`, `NewEdit`, `Detail`, `Select`
- For pop-up pages, prefix with `Popup_`

### Examples

- Good: `Order_Overview`, `Customer_NewEdit`, `Product_Detail`
- Bad: `Page1`, `MyPage`, `OrdersListPage`

## Module Naming

Modules should use PascalCase and represent a functional domain.

### Rules

- Use PascalCase
- Use descriptive functional names
- Keep module names concise but clear
- Avoid technical prefixes

### Examples

- Good: `Administration`, `OrderManagement`, `CustomerPortal`
- Bad: `mod_admin`, `Module1`, `MyApp_Orders`
