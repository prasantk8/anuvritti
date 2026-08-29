# The Ethical Constitution, as tests

PRD §47 calls its boundaries "constitutional". A boundary that lives only in a document
drifts; a boundary with a failing test does not.

These tests are deliberately awkward to satisfy. If one starts failing, the correct
response is almost never to change the test — it is to ask whether the product just
crossed a line the founder said it would not cross.

| File | Enforces |
|---|---|
| `test_no_guilt.py` | §8.5 — no guilt, no fake urgency, no nagging |
| `test_no_surveillance.py` | §46 — never child GPS, screen spying or behavioural scoring |
| `test_v0_scope.py` | §49 — the things V0 deliberately does not build |
| `test_ai_honesty.py` | §8.7, §13 — AI interpretation is never presented as truth |
| `test_film_provenance.py` | §8.7, §47 — a film may only claim what the archive can show |
| `test_real_voice.py` | §12, §39, §47 — the voice in a family's film is the family's voice |
| `test_inbox_sealed.py` | §20, §44, §47 — exact sealed messages; sensitive openings stay human |
