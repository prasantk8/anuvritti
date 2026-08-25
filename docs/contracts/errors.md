# Error Catalog (contract)

Every application failure is a `DomainError` with a stable `code`. The HTTP adapter is the only
place that maps a code to a status. Clients switch on `code`, never on prose.

Wire shape (always exactly this shape):

```json
{ "error": { "code": "SPARK_INVALID_TRANSITION", "message": "human readable", "details": {} } }
```

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_FAILED` | 422 | Input violated a value-object invariant |
| `FAMILY_NOT_FOUND` | 404 | No such family |
| `MEMBER_NOT_FOUND` | 404 | No such member |
| `CHILD_NOT_FOUND` | 404 | No such child profile |
| `SPARK_NOT_FOUND` | 404 | No such Spark, or not visible to the actor |
| `MOMENT_NOT_FOUND` | 404 | No such Moment |
| `MEDIA_NOT_FOUND` | 404 | No such media object |
| `SPARK_INVALID_TRANSITION` | 409 | Lifecycle transition not permitted from current status |
| `SPARK_ARCHIVED` | 409 | Spark was marked "not relevant anymore" |
| `PERMISSION_DENIED` | 403 | Actor's role/visibility does not permit this |
| `CAPTURE_SOURCE_INVALID` | 422 | Source payload unusable (malformed URL, empty text) |
| `MEDIA_TOO_LARGE` | 413 | Exceeds `ANUVRITTI_MAX_MEDIA_BYTES` |
| `MEDIA_KIND_UNSUPPORTED` | 415 | MIME type not on the allow-list |
| `CONFLICT` | 409 | Uniqueness or concurrency conflict |

The Return Engine returning **nothing** is a normal, silent, guilt-free outcome (PRD §8.5).
It is never an error and never produces a message.
