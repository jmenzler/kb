# Workflows

Step-by-step procedures Claude reads and follows for KB maintenance: creating a KB, bootstrapping one from a
codebase, capturing, cleaning, and managing sources. They are plain markdown rather than skills so that one
skill (`kb:base`, or `kb:clean` / `kb:capture`) can route to them on demand instead of every procedure sitting in
context all the time.

`capture.md` is the single rulebook for staging knowledge — both the manual `kb:capture` path and the automatic
capture fork follow it — and `clean.md` owns the shared reconcile protocol that `full-clean.md` reuses. Writing
style for anything that ends up in a KB is in `../STYLE.md`.
