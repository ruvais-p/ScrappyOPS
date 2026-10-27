"""Every table the pages may write to, with the rules for it. A table that is not listed cannot be written to at all."""
from kwd.rules.days import ExpenseItems, FieldDays
from kwd.rules.franchise import (FrCompanySettings, FrFranchises, FrLeads, FrMeetings, FrPresentations, FrProducts, FrSales, FrStockMoves, FrTargets)
from kwd.rules.simple import (Contacts, Districts, ExpensePolicy, Followups, Lsgds, Opportunities, Profiles, Tasks, UserDistricts,
                              VerificationCalls)
from kwd.rules.visits import Visits, VisitContacts

RULES = {r.api: r for r in (
    Districts(), Profiles(), UserDistricts(), Lsgds(), Contacts(), Tasks(), Opportunities(), Followups(), VerificationCalls(),
    ExpensePolicy(), Visits(), VisitContacts(), FieldDays(), ExpenseItems(), FrFranchises(), FrProducts(), FrTargets(), FrLeads(),
    FrPresentations(), FrSales(), FrStockMoves(), FrCompanySettings(), FrMeetings(),
)}
