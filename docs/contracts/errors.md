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
| `UNAUTHENTICATED` | 401 | No device token, or the token is unknown or revoked |
| `PAIRING_FAILED` | 401 | The pairing code did not work. Deliberately one code for wrong, expired, already-used and locked-out — telling them apart tells an attacker which codes exist |
| `PERMISSION_DENIED` | 403 | Actor's role/visibility does not permit this, or the request named a family the token does not belong to |
| `CAPTURE_SOURCE_INVALID` | 422 | Source payload unusable (malformed URL, empty text) |
| `MEDIA_TOO_LARGE` | 413 | Exceeds `ANUVRITTI_MAX_MEDIA_BYTES` |
| `MEDIA_KIND_UNSUPPORTED` | 415 | MIME type not on the allow-list |
| `FILM_NOT_COMPILABLE` | 422 | The film does not add up: no scenes, a scene id used twice, or a scene that would have to be cut off to fit its cap |
| `CONFLICT` | 409 | Uniqueness or concurrency conflict |
| `TOO_MANY_REQUESTS` | 429 | Rate limit exceeded. Please wait before retrying |
| `BACKUP_INCOMPLETE` | — | Operational only, never on the wire: a backup or restore is missing a file its manifest promises (`adapters/backup.py`) |

The Return Engine returning **nothing** is a normal, silent, guilt-free outcome (PRD §8.5).
It is never an error and never produces a message.
