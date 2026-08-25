# Domain Events (contract)

In-process, append-only, persisted to `domain_event`. They are the audit trail required by §44
("auditable changes") and the source of the §53 metrics.

| Event | Emitted when | Payload |
|---|---|---|
| `SparkCaptured` | Spark created | `spark_id, family_id, owner_id, subject_child_id, source_kind` |
| `SparkEnriched` | IntentEngine inference applied | `spark_id, intent, confidence, category` |
| `SparkWhyRecorded` | Human "why" attached (§12) | `spark_id, has_voice` |
| `SparkFieldOverridden` | Human corrected an AI field | `spark_id, field` |
| `SparkSuggested` | Return Engine surfaced it | `spark_id, score, reason_key, days_since_capture` |
| `SparkSnoozed` | "Maybe later" | `spark_id, snoozed_until` |
| `SparkArchived` | "Not relevant anymore" | `spark_id` |
| `SparkPlanned` | "Let's do it" | `spark_id` |
| `MomentCreated` | Spark became lived life (§15) | `moment_id, spark_id, days_from_capture, has_photo, has_audio, has_reflection` |
| `LittleThingCaptured` | One-tap note (§17) | `little_thing_id, has_audio` |
| `RightNowCaptured` | Micro-snapshot (§18) | `right_now_id, child_id, prompt` |
| `VoiceNoteKept` | A recording was kept (§12, §17, §21) | `media_id` |
| `VoiceNoteIndexed` | A transcript was attached (§8.7) | `media_id, engine, source` |
| `FamilyDataExported` | Export requested (§44) | `family_id, spark_count, media_count` |
| `FamilyDataDeleted` | Erasure requested (§44) | `family_id, deleted_counts` |

`VoiceNoteKept` deliberately carries no duration. It is the one obvious field to add here and
the one that would turn the audit trail into something totalable — "you recorded four minutes
this month" is a scorecard about a parent's attention to their own child (§8.5). The duration
lives on the recording, where the film that has to measure it can read it.

**No event carries free-text child content.** Payloads are structural only — the audit log must
not become a shadow copy of the family archive.

## Metric derivation (§53)

- **Intent → Moment conversion** = `count(MomentCreated) / count(SparkCaptured)`.
- **Sparks resurfaced** = `count(distinct spark_id in SparkSuggested)`.
- **Anti-metric — notification volume** = `count(SparkSuggested)`; the target is *low*.
