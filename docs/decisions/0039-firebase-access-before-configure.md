# 0039 — Firebase calls in property defaults fire before configure()
Date: 2026-05-31  •  Status: Decided (guidance)

## Context
During P3, the app crashed at launch: Auth.auth() asserts FirebaseApp is
configured. The offending calls were in stored-property / @Published default
values (e.g. `@Published var uid = Auth.auth().currentUser?.uid`) and in
`.shared` accesses used as default parameter values in initializers.

## What was wrong
Swift evaluates stored-property initializers and default parameter expressions
BEFORE the enclosing init() body runs. A guard placed in init() does not protect
a Firebase call in a property's default value — the property initializer runs
first, before configure(), and trips Firebase's "app not configured" assertion.

## What we chose
- Never call Auth.auth() / FirebaseApp.app() / currentUser in a stored-property
  or @Published default value. Assign those in the init() body (or lazily),
  after a configured check.
- Do not put `.shared` singletons that touch Firebase in default parameter
  expressions; resolve them inside the init() body.
- FirebaseApp.configure() runs once at app launch; all Firebase access is gated
  on it.

## Why
This is an ordering trap invisible at the call site — the code reads as guarded
but the guard is in the wrong scope relative to property initialization. It will
recur for anyone adding a Firebase-touching property or a Firebase-backed
singleton with a default-parameter injection point.

## What would change this decision
If the app moves to a DI container that constructs Firebase-dependent objects
only after configure(), the default-value hazard goes away for those objects and
the rule narrows to top-level/global initializers.
