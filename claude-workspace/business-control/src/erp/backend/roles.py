"""Who may confer what on whom — the school's role matrix, ported from
lingua-portal's roles.py.

Pure: no database, no request, no clock. Every rule here is a function of
role names and two flags, so the whole permission matrix can be enumerated
in a test rather than sampled. Authorisation is the one place where "we
checked the cases we thought of" is not good enough.

The shape, in one paragraph. Whoever holds the admin flag (the owner, or an
approved **executive director**) manages everyone. **Office staff** — this
platform's `employee` role — run the school day to day: they approve and
manage students, teachers and volunteers, and nothing else. **Board**
members and **donor** records are the most sensitive rows a school holds
and staff have no operational need for them, so only the admin may confer
or even review those. Students, teachers and volunteers manage nobody.

The platform note: this module maps the source's seven school roles onto
business-control's own words. A student IS a customer — the storefront's
existing meaning, unchanged — and the source's "administrator / staff" IS
this platform's `employee`. The other five are new role values. There is
deliberately no superuser branch: the admin flag's power is spelled out as
data in MANAGES like everybody else's, so reading this file tells the whole
truth without also knowing which checks a special case skips.
"""

# ── the roles ────────────────────────────────────────────────────────────────
STUDENT = "customer"           # the storefront's own word for it
TEACHER = "teacher"
VOLUNTEER = "volunteer"
STAFF = "employee"             # "administrator / staff" — the office role
DIRECTOR = "director"          # executive director; approval carries admin
BOARD = "board"                # board member
DONOR = "donor"

ROLES = (STUDENT, TEACHER, VOLUNTEER, STAFF, DIRECTOR, BOARD, DONOR)

LABELS = {
    STUDENT: "Student",
    TEACHER: "Teacher",
    VOLUNTEER: "Volunteer",
    STAFF: "Administrator / staff",
    DIRECTOR: "Executive director",
    BOARD: "Board member",
    DONOR: "Donor",
}

# What each role is for, shown on the sign-up dropdown so somebody picks
# the right one.
DESCRIPTIONS = {
    STUDENT: "I want to take classes",
    TEACHER: "I teach classes",
    VOLUNTEER: "I help out",
    STAFF: "I work in the office",
    DIRECTOR: "I run the organisation",
    BOARD: "I sit on the board",
    DONOR: "I support the organisation",
}

# Roles ONLY the admin may confer or review. Who funds an organisation and
# who governs it are the most sensitive records here, and office staff have
# no operational reason to touch them.
RESTRICTED = frozenset({BOARD, DONOR})

# role -> the requested roles it may grant or decline. The admin flag adds
# everything; a role that could widen its own reach would be a
# privilege-escalation ladder with one rung, so nothing below the flag
# confers STAFF, DIRECTOR, or the RESTRICTED pair.
MANAGES = {
    STAFF: frozenset({STUDENT, TEACHER, VOLUNTEER}),
    STUDENT: frozenset(),
    TEACHER: frozenset(),
    VOLUNTEER: frozenset(),
    DIRECTOR: frozenset(),     # without the flag the ROLE grants nothing —
    BOARD: frozenset(),        # approval sets the flag, and the flag rules
    DONOR: frozenset(),
}


def grantable_by(role: str, *, is_admin: bool = False) -> frozenset:
    """Every requested role this actor may grant or decline."""
    if is_admin:
        return frozenset(ROLES)
    return MANAGES.get(role, frozenset())


def is_reviewer(role: str, *, is_admin: bool = False) -> bool:
    """Can this actor see the role-request queue at all?"""
    return bool(grantable_by(role, is_admin=is_admin))


def can_grant(actor, wanted: str) -> bool:
    """May this actor CONFER `wanted` — approve the request, or decline it?

    Declining takes the same right as approving, and that is the point: an
    office administrator who cannot make a director must not be able to
    silently bury a director request either — it stays visible to whoever
    can decide it.
    """
    return wanted in grantable_by(actor["role"],
                                  is_admin=bool(actor["is_admin"]))


def carries_admin(role: str) -> bool:
    """Approving this role also sets the admin flag. Only the executive
    director: running the organisation IS the admin surface here."""
    return role == DIRECTOR


def claimable(role: str) -> bool:
    """May sign-up ASK for this role? Everything but student — a student
    claim is not a claim, it is the default everyone starts as."""
    return role in ROLES and role != STUDENT


def normalise(role: str, default: str = STUDENT) -> str:
    r = str(role or "").strip().lower()
    if r == "student":
        return STUDENT
    if r == "staff":
        return STAFF
    return r if r in ROLES else default
