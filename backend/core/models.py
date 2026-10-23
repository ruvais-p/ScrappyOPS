"""Database tables. Names and columns match the Supabase project they replace, so data can be copied across
as it is (see the import_from_supabase command). Business rules live in core/services; this file holds the
shape of the data and the rules the database itself can enforce (checks, uniqueness, immutable records)."""
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now, Round


# ----------------------------------------------------------------------------------------------
# logins
# ----------------------------------------------------------------------------------------------
class UserManager(BaseUserManager):
    def create_user(self, email, password=None):
        email = (email or "").strip().lower()
        if not email:
            raise ValueError("An email is required.")
        user = self.model(email=email)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """A login (email + password). The person's role, name and franchise are on Profile."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    objects = UserManager()

    class Meta:
        db_table = "users"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)


class AuthSession(models.Model):
    """One open login on one device. A new login removes the person's other sessions (newest login wins)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    refresh_hash = models.CharField(max_length=64, unique=True)
    recent = models.JSONField(default=list)          # [[hash, replaced_at_epoch], ...] for the short reuse window
    created_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "auth_sessions"


# ----------------------------------------------------------------------------------------------
# helpers: records that can never be edited
# ----------------------------------------------------------------------------------------------
class ImmutableError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableError("This record cannot be changed or deleted.")

    def delete(self):
        raise ImmutableError("This record cannot be changed or deleted.")

    def bulk_update(self, *a, **k):
        raise ImmutableError("This record cannot be changed or deleted.")


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableError("This record cannot be changed or deleted.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError("This record cannot be changed or deleted.")


class Counter(models.Model):
    """Running numbers for the readable codes: SC-1001, LD-0001, SB-000001, RQ-0001, RL-0301."""
    name = models.CharField(max_length=40, primary_key=True)
    value = models.BigIntegerField(default=0)

    class Meta:
        db_table = "counters"


def next_number(name):
    """Next value of a counter. Call inside a transaction: the row is locked until it ends, so numbers never repeat."""
    c = Counter.objects.select_for_update().get(name=name)
    c.value += 1
    c.save(update_fields=["value"])
    return c.value


# ----------------------------------------------------------------------------------------------
# franchises and people
# ----------------------------------------------------------------------------------------------
class Franchise(models.Model):
    code = models.CharField(max_length=12, unique=True)
    name = models.TextField()
    district = models.TextField(null=True, blank=True)
    constituency = models.TextField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "franchises"
        constraints = [
            models.CheckConstraint(condition=Q(code__regex=r"^[A-Z0-9][A-Z0-9-]{1,11}$"), name="franchise_code_format"),
        ]


ROLES = ("driver", "hq", "warehouse", "supervisor")


class Profile(models.Model):
    """id is the login's id. Role: driver (collector), warehouse (warehouse manager), supervisor, hq."""
    user = models.OneToOneField(User, primary_key=True, on_delete=models.CASCADE, db_column="id", related_name="profile")
    full_name = models.TextField()
    phone = models.TextField(null=True, blank=True)
    role = models.TextField()
    territory = models.TextField(null=True, blank=True)
    vehicle_no = models.TextField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    franchise = models.ForeignKey(Franchise, null=True, blank=True, on_delete=models.PROTECT, related_name="people")

    class Meta:
        db_table = "profiles"
        indexes = [models.Index(fields=["franchise"], name="profiles_franchise_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(role__in=ROLES), name="profiles_role_check"),
            models.CheckConstraint(condition=Q(role="hq") | Q(franchise__isnull=False), name="profiles_franchise_check"),
        ]


class Customer(models.Model):
    name = models.TextField()
    phone = models.TextField()
    address = models.TextField()
    area = models.TextField(null=True, blank=True)
    upi_id = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customers"


class ScrapItem(models.Model):
    name = models.TextField()
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "scrap_items"


class Rate(models.Model):
    """Price history. The newest rate whose effective_from has passed is the current one."""
    item = models.ForeignKey(ScrapItem, on_delete=models.CASCADE, related_name="rates")
    rate_per_kg = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateTimeField(db_default=Now())     # the database clock, so "current rate" never disagrees with it
    set_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, db_column="set_by")

    class Meta:
        db_table = "rates"
        constraints = [models.CheckConstraint(condition=Q(rate_per_kg__gt=0), name="rates_positive")]


# ----------------------------------------------------------------------------------------------
# pickups
# ----------------------------------------------------------------------------------------------
LEAD_STATUSES = ("unassigned", "scheduled", "in_progress", "closed", "cancelled", "failed")


class Lead(models.Model):
    code = models.TextField(unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    driver = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.PROTECT, related_name="leads")
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT, related_name="leads")
    slot = models.DateTimeField(null=True, blank=True)
    items_said = models.TextField(null=True, blank=True)
    status = models.TextField(default="scheduled")
    created_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="created_by")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    fail_reason = models.TextField(null=True, blank=True)
    fail_note = models.TextField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leads"
        indexes = [
            models.Index(fields=["franchise", "status"], name="leads_franchise_idx"),
            models.Index(fields=["driver"], name="leads_driver_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=LEAD_STATUSES), name="leads_status_check"),
            models.CheckConstraint(condition=Q(driver__isnull=False) | Q(status__in=("unassigned", "cancelled")), name="leads_driver_check"),
            models.CheckConstraint(
                condition=(Q(latitude__isnull=True) & Q(longitude__isnull=True)) | (Q(latitude__isnull=False) & Q(longitude__isnull=False)),
                name="leads_location_check"),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"SC-{next_number('lead_code')}"
        super().save(*args, **kwargs)


class Load(models.Model):
    """A driver's route: all the pickups between leaving and ending the route."""
    code = models.TextField(unique=True)
    driver = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="loads")
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT, related_name="loads")
    vehicle_no = models.TextField(null=True, blank=True)
    status = models.TextField(default="open")
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    warehouse_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    checked_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="checked_by")
    weighed_at = models.DateTimeField(null=True, blank=True)
    weighing_note = models.TextField(null=True, blank=True)
    resolved_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="resolved_by")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "loads"
        indexes = [
            models.Index(fields=["franchise", "status"], name="loads_franchise_idx"),
            models.Index(fields=["driver", "status"], name="loads_driver_idx"),
            models.Index(fields=["started_at"], name="loads_started_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("open", "submitted", "reconciled", "flagged")), name="loads_status_check"),
            models.UniqueConstraint(fields=["driver"], condition=Q(status="open"), name="one_open_load_per_driver"),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"LD-{next_number('load_code'):04d}"
        super().save(*args, **kwargs)


class Bill(models.Model):
    bill_no = models.TextField(unique=True)
    lead = models.OneToOneField(Lead, on_delete=models.PROTECT, related_name="bill")
    load = models.ForeignKey(Load, on_delete=models.PROTECT, related_name="bills")
    status = models.TextField(default="draft")            # draft -> sent -> confirmed -> paid
    sent_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.TextField(null=True, blank=True)
    upi_ref = models.TextField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirm_proof_url = models.TextField(null=True, blank=True)
    whatsapp_opened_at = models.DateTimeField(null=True, blank=True)
    pdf_path = models.TextField(null=True, blank=True)
    share_token = models.UUIDField(default=uuid.uuid4, unique=True)

    class Meta:
        db_table = "bills"
        indexes = [models.Index(fields=["load"], name="bills_load_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("draft", "sent", "confirmed", "paid")), name="bills_status_check"),
            models.CheckConstraint(condition=Q(payment_method__isnull=True) | Q(payment_method__in=("upi", "cash")), name="bills_method_check"),
        ]

    def save(self, *args, **kwargs):
        if not self.bill_no:
            self.bill_no = f"SB-{next_number('bill_no'):06d}"
        super().save(*args, **kwargs)


class BillItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(ScrapItem, on_delete=models.PROTECT)
    qty_kg = models.DecimalField(max_digits=12, decimal_places=3)
    rate_per_kg = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.GeneratedField(
        expression=Round(F("qty_kg") * F("rate_per_kg"), 2),
        output_field=models.DecimalField(max_digits=14, decimal_places=2), db_persist=True)
    photo_url = models.TextField(null=True, blank=True)
    typed_by_hand = models.BooleanField(default=False)

    class Meta:
        db_table = "bill_items"
        indexes = [models.Index(fields=["bill"], name="bill_items_bill_idx")]
        constraints = [
            models.UniqueConstraint(fields=["bill", "item"], name="bill_items_bill_item_uq"),
            models.CheckConstraint(condition=Q(qty_kg__gt=0), name="bill_items_qty_positive"),
        ]


class CashLedgerQuerySet(AppendOnlyQuerySet):
    pass


class CashLedger(AppendOnlyModel):
    """Every rupee a collector holds. Rows are only ever added; a mistake is fixed with a correcting row."""
    driver = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="ledger")
    entry_type = models.TextField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.PROTECT)
    note = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="created_by")
    created_at = models.DateTimeField(auto_now_add=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)

    class Meta:
        db_table = "cash_ledger"
        indexes = [
            models.Index(fields=["driver", "created_at"], name="cash_ledger_driver_created_idx"),
            models.Index(fields=["franchise"], name="cash_ledger_franchise_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(entry_type__in=("float_issued", "cash_payout", "handover")), name="cash_ledger_entry_type_check"),
            models.CheckConstraint(
                condition=(Q(entry_type="float_issued") & Q(amount__gt=0)) | (Q(entry_type__in=("cash_payout", "handover")) & Q(amount__lt=0)),
                name="cash_ledger_sign_check"),
            models.CheckConstraint(condition=~Q(entry_type="cash_payout") | Q(bill__isnull=False), name="cash_ledger_payout_has_bill"),
        ]


class LeadImport(models.Model):
    """The upload inbox for HQ's Excel sheet. Every row is checked as it is added and gets a result."""
    customer_name = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    area = models.TextField(null=True, blank=True)
    upi_id = models.TextField(null=True, blank=True)
    driver_email = models.TextField(null=True, blank=True)
    pickup_date = models.TextField(null=True, blank=True)
    pickup_time = models.TextField(null=True, blank=True)
    items = models.TextField(null=True, blank=True)
    status = models.TextField(default="new")
    message = models.TextField(null=True, blank=True)
    lead_code = models.TextField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    latitude = models.TextField(null=True, blank=True)
    longitude = models.TextField(null=True, blank=True)
    franchise_code = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "lead_import"


# ----------------------------------------------------------------------------------------------
# warehouse
# ----------------------------------------------------------------------------------------------
class WeighingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if set(kwargs) != {"superseded_at"}:
            raise ImmutableError("Weighing records cannot be edited. Re-weigh the load instead.")
        return super().update(**kwargs)

    def delete(self):
        raise ImmutableError("Weighing records cannot be deleted.")


class LoadWeighing(models.Model):
    """The warehouse weight of one material in one load. A re-weigh marks the old row superseded and adds new rows."""
    load = models.ForeignKey(Load, on_delete=models.PROTECT, related_name="weighings")
    item = models.ForeignKey(ScrapItem, on_delete=models.PROTECT)
    billed_kg = models.DecimalField(max_digits=14, decimal_places=3)
    warehouse_kg = models.DecimalField(max_digits=14, decimal_places=3)
    within_tolerance = models.BooleanField()
    weighed_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+", db_column="weighed_by")
    weighed_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)

    objects = WeighingQuerySet.as_manager()

    class Meta:
        db_table = "load_weighings"
        indexes = [
            models.Index(fields=["item"], name="load_weighings_item_idx"),
            models.Index(fields=["load"], name="load_weighings_load_idx"),
            models.Index(fields=["franchise"], name="load_weighings_franchise_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["load", "item"], condition=Q(superseded_at__isnull=True), name="load_weighings_current_uq"),
            models.CheckConstraint(condition=Q(billed_kg__gte=0) & Q(warehouse_kg__gte=0), name="load_weighings_kg_check"),
        ]

    def delete(self, *a, **k):
        raise ImmutableError("Weighing records cannot be deleted.")


class HqRequirement(models.Model):
    code = models.TextField(unique=True)
    item = models.ForeignKey(ScrapItem, on_delete=models.PROTECT)
    required_kg = models.DecimalField(max_digits=14, decimal_places=3)
    due_date = models.DateField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    status = models.TextField(default="open")
    raised_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="raised_by")
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_note = models.TextField(null=True, blank=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)

    class Meta:
        db_table = "hq_requirements"
        indexes = [models.Index(fields=["franchise", "status"], name="hq_requirements_franchise_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(required_kg__gt=0), name="hq_requirements_kg_check"),
            models.CheckConstraint(condition=Q(status__in=("open", "cancelled")), name="hq_requirements_status_check"),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"RQ-{next_number('requirement_code'):04d}"
        super().save(*args, **kwargs)


class HqRelease(AppendOnlyModel):
    code = models.TextField(unique=True)
    requirement = models.ForeignKey(HqRequirement, on_delete=models.PROTECT, related_name="releases")
    item = models.ForeignKey(ScrapItem, on_delete=models.PROTECT)
    kg = models.DecimalField(max_digits=14, decimal_places=3)
    vehicle_no = models.TextField()
    note = models.TextField(null=True, blank=True)
    released_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+", db_column="released_by")
    released_at = models.DateTimeField(auto_now_add=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)

    class Meta:
        db_table = "hq_releases"
        indexes = [
            models.Index(fields=["requirement"], name="hq_releases_req_idx"),
            models.Index(fields=["item"], name="hq_releases_item_idx"),
            models.Index(fields=["franchise"], name="hq_releases_franchise_idx"),
        ]
        constraints = [models.CheckConstraint(condition=Q(kg__gt=0), name="hq_releases_kg_check")]

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = f"RL-{next_number('release_code'):04d}"
        super().save(*args, **kwargs)


class HqBuyRate(models.Model):
    """What HQ pays a franchise per kg for each material (the sale price of the franchise's stock). Price history: the newest
    rate whose effective_from has passed is the current one. Only HQ sets it; supervisors read it, warehouse managers never see it."""
    item = models.ForeignKey(ScrapItem, on_delete=models.CASCADE, related_name="buy_rates")
    rate_per_kg = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateTimeField(db_default=Now())
    set_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="set_by")

    class Meta:
        db_table = "hq_buy_rates"
        constraints = [models.CheckConstraint(condition=Q(rate_per_kg__gt=0), name="hq_buy_rates_positive")]


DISPATCH_STATUSES = ("pending", "finalized", "rejected", "withdrawn")


class HqDispatch(models.Model):
    """One vehicle load of stock going to HQ. The warehouse manager enters the quantity of each material and sends it to the
    supervisor (pending); the supervisor finalizes it (which records the releases and the price) or sends it back (rejected)."""
    code = models.TextField(unique=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)
    vehicle_no = models.TextField()
    status = models.TextField(default="pending")
    note = models.TextField(null=True, blank=True)
    prepared_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+", db_column="prepared_by")
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="reviewed_by")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hq_dispatches"
        indexes = [models.Index(fields=["franchise", "status"], name="hq_dispatches_franchise_idx")]
        constraints = [models.CheckConstraint(condition=Q(status__in=DISPATCH_STATUSES), name="hq_dispatches_status_check")]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"DP-{next_number('dispatch_code'):04d}"
        super().save(*args, **kwargs)


class HqDispatchLine(models.Model):
    dispatch = models.ForeignKey(HqDispatch, on_delete=models.CASCADE, related_name="lines")
    requirement = models.ForeignKey(HqRequirement, on_delete=models.PROTECT, related_name="+")
    item = models.ForeignKey(ScrapItem, on_delete=models.PROTECT, related_name="+")
    kg = models.DecimalField(max_digits=14, decimal_places=3)
    price_per_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)     # fixed when the supervisor finalizes
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    release = models.ForeignKey(HqRelease, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "hq_dispatch_lines"
        constraints = [
            models.CheckConstraint(condition=Q(kg__gt=0), name="hq_dispatch_lines_kg_check"),
            models.UniqueConstraint(fields=["dispatch", "requirement"], name="hq_dispatch_lines_once"),
        ]


class CashSettlement(models.Model):
    """The cash a collector handed back at the warehouse, counted by one person and verified by another."""
    load = models.OneToOneField(Load, on_delete=models.PROTECT, related_name="settlement")
    driver = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="settlements")
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2)
    counted_cash = models.DecimalField(max_digits=14, decimal_places=2)
    difference = models.GeneratedField(
        expression=F("counted_cash") - F("expected_cash"),
        output_field=models.DecimalField(max_digits=14, decimal_places=2), db_persist=True)
    cash_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    upi_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.TextField(default="counted")
    counted_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+", db_column="counted_by")
    counted_at = models.DateTimeField(auto_now_add=True)
    count_note = models.TextField(null=True, blank=True)
    verified_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.PROTECT, related_name="+", db_column="verified_by")
    verified_at = models.DateTimeField(null=True, blank=True)
    verify_note = models.TextField(null=True, blank=True)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)
    covered_load_ids = ArrayField(models.IntegerField(), default=list)

    class Meta:
        db_table = "cash_settlements"
        indexes = [
            models.Index(fields=["driver"], name="cash_settlements_driver_idx"),
            models.Index(fields=["franchise"], name="cash_settlements_franchise_idx"),
            GinIndex(fields=["covered_load_ids"], name="cash_settlements_covered_gin"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("counted", "verified", "disputed")), name="cash_settlements_status_check"),
            models.CheckConstraint(condition=Q(verified_by__isnull=True) | ~Q(verified_by=F("counted_by")), name="settle_two_people"),
            models.CheckConstraint(condition=Q(expected_cash__gte=0) & Q(counted_cash__gte=0), name="cash_settlements_amounts_check"),
        ]

    def delete(self, *a, **k):
        raise ImmutableError("Cash settlements cannot be deleted.")


class SettlementResolution(AppendOnlyModel):
    settlement = models.OneToOneField(CashSettlement, on_delete=models.PROTECT, related_name="resolution")
    decision = models.TextField()
    note = models.TextField()
    resolved_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+", db_column="resolved_by")
    resolved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settlement_resolutions"
        constraints = [
            models.CheckConstraint(condition=Q(decision__in=("recover_from_driver", "write_off", "no_action")), name="settlement_decision_check"),
            models.CheckConstraint(condition=~Q(note=""), name="settlement_note_check"),
        ]


class HqAudit(AppendOnlyModel):
    """The activity log: who did what. Cannot be edited."""
    at = models.DateTimeField(auto_now_add=True)
    by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", db_column="by_id")
    action = models.TextField()
    ref = models.TextField(null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)
    franchise = models.ForeignKey(Franchise, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = "hq_audit"
        indexes = [models.Index(fields=["franchise"], name="hq_audit_franchise_idx")]
