# Logging Levels Specification

## code-error

Use when:
- the system failed unexpectedly
- code behavior is invalid
- execution cannot complete correctly
- data integrity may be affected
- a bug, crash, exception, or internal failure occurred

Meaning:
- this is a system or code failure
- developer attention is required
- the behavior was not intended or acceptable

Rules:
- never use for user mistakes
- never use for expected denial flows
- should represent genuine failures

---

## warning

Use when:
- the system intentionally refuses an action
- access, execution, or continuation is denied
- security, permission, policy, or limit rules activated
- the operation cannot continue by design

Meaning:
- the system is functioning correctly
- the action was prevented intentionally
- the failure is expected behavior

Rules:
- use for bans, rate limits, permission denial, locked resources, process unable to continue
- do not use for crashes or broken code
- do not use when execution still succeeds
- do not use for normal events

---

## notify

Use when:
- an important event occurred
- the event should be recorded for audit, tracking, or visibility
- humans may want to review the event later
- the event is significant but not problematic

Meaning:
- this is informational but important
- no failure or degradation occurred
- the event matters operationally or historically

Rules:
- use for security-sensitive actions and major state changes
- do not use for routine spam-level activity
- should remain readable and useful

---

## normal-operation

Use when:
- routine system activity occurs
- standard execution paths complete normally
- low-importance operational tracking is needed
- detailed flow visibility is desired

Meaning:
- the system is functioning normally
- no issue or special condition exists
- this is ordinary runtime behavior
- logs for when an opration has been completed

Rules:
- highest volume logging tier
- should contain only useful operational detail
- avoid excessive noise or redundant spam


# Logging

# Required Fields

| Field | Description |
|---|---|
| timestamp | exact UTC time of event |
| level | code-error, warning, notify, normal-operation |
| folder | source folder where event originated |
| file | source file name |
| line | source code line number (if possible) |
| raw_error | full unmodified error output/stack trace |
| message | human-readable description of the event |

The database table also includes `id` (auto-increment primary key) and `created_at` (auto-set timestamp).
