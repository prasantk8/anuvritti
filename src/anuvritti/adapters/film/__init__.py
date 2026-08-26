"""Film compilation adapters.

Deliberately not imported by `interfaces.http.container`. The composition root that boots
the family's always-on server must never reach this package, and a test in
`tests/unit/application/test_film.py` walks the import graph to prove it still doesn't.
"""
