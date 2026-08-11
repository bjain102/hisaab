"""Schema migrations (ADR-007). One module per version, named m###_short_name.py
(m001_accounts.py -> version 1). Each module exposes:

    def up(conn):      # transform the schema/data; conn is inside a transaction
    def verify(conn):  # raise (any exception) if the result is wrong

Both run in ONE transaction per migration — a verify failure rolls everything
back including the version bump. Never edit or renumber a migration that has
already run against the real DB; add a new one instead.

Empty as of task 3.1 (the runner ships first); v1 lands with task 3.2.
"""
