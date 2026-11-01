### Error Collection Contract

The document pipeline collects validation and synchronization errors from individual services into two unified dictionaries:

```python
errors = {}
row_errors = {}
```

#### Header / document errors

Header-level services return:

```python
{
    "errors": {
        "partner": ["Partner is required."],
        "date": ["Invalid date."]
    }
}
```

The pipeline calls:

```python
self._collect(
    errors,
    header_result,
    key="errors",
)
```

The result is merged into the pipeline's `errors` dictionary.

The structure is:

```text
errors
└── field
    └── list of messages
```

Example:

```python
{
    "partner": ["Partner is required."],
    "date": ["Invalid date."]
}
```

If multiple services report an error for the same field, their messages are appended rather than replacing the existing messages.

---

#### Row / line errors

Line services return errors grouped by the row prefix:

```python
{
    "row_errors": {
        "items-0": {
            "account": ["Select a valid account."]
        },
        "items-2": {
            "debit": ["Enter a valid amount."]
        }
    }
}
```

The pipeline calls:

```python
self._collect(
    row_errors,
    items_result,
    key="row_errors",
)
```

The resulting structure is:

```text
row_errors
└── row prefix
    └── field
        └── list of messages
```

For example:

```python
{
    "items-0": {
        "account": ["Select a valid account."]
    },
    "items-2": {
        "debit": ["Enter a valid amount."]
    }
}
```

The row prefix is important because it allows the presentation layer to associate an error with the correct Django form in the formset.

---

#### Field-name translation

Services may use database-oriented names such as:

```python
account_id
partner_id
payment_term_id
```

while Django forms expose:

```python
account
partner
payment_term
```

The individual service is responsible for translating its service/model field name into the form field name before returning errors.

For example:

```python
{
    "account_id": ["Select a valid account."]
}
```

becomes:

```python
{
    "account": ["Select a valid account."]
}
```

The pipeline therefore does not perform FK-specific error translation. It only collects already-normalized errors.

---

#### Error collection does not validate

`DocumentService._collect()` does not create or interpret validation errors.

Its only responsibility is to merge errors returned by collaborating services.

The flow is:

```text
Service
   │
   │ validates / catches errors
   ▼
Service result
   │
   │ errors / row_errors
   ▼
DocumentService._collect()
   │
   ▼
Unified pipeline errors
   │
   ▼
DocumentSnapshot
   │
   ▼
DocumentUIService
   │
   ▼
UIResponseService
   │
   ▼
Django form / HTMX response
```

---

#### Error shapes

The pipeline maintains two distinct error shapes:

```python
# Header/document errors
errors = {
    "field": ["message"]
}
```

and:

```python
# Row/line errors
row_errors = {
    "row-prefix": {
        "field": ["message"]
    }
}
```

This distinction should be preserved throughout the pipeline because header errors attach directly to the document form, while row errors must first be associated with a specific formset row.

---

#### Structural row errors

`row_errors` may also contain structural information that is not a normal form error.

For example:

```python
{
    "location_deleted_items": [12, 15]
}
```

Such entries are not treated as field errors and must not be injected into a Django form.

`_collect()` therefore ignores row-error values that are not dictionaries when merging form-level row errors.

The final pipeline is responsible for deciding whether such structural information should affect the snapshot or UI plan.