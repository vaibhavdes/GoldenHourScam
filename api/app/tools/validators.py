"""Format checks against independent source text, or explicitly user-entered values."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import PurePath

from app.models import Case, Field_, Rail, Transaction
from app.packs import load_pack


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").replace(",", "").strip().casefold()


def grounded(field: Field_, text: str | None = None, *, amount: bool = False, timestamp: bool = False) -> bool:
    """Never use the extractor's quote as proof. Numeric IDs require token boundaries."""
    if not field.value or not text:
        return False
    value, source = _norm(field.value), _norm(text)
    if timestamp:
        try:
            target = datetime.fromisoformat(field.value)
        except ValueError:
            return False
        # Compare a complete visible date+time, not isolated hour/day digits or
        # the extractor's quote. Screenshots normally display local time, not ISO.
        candidates = re.findall(r"\b(?:\d{1,2}[ /-][A-Za-z]{3,9}[ ,/-]+\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})[, ]+(?:at )?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?\b", text)
        dates = ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%b-%y", "%d-%m-%y")
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate.replace(",", " ").replace(" at ", " ")).strip()
            for date in dates:
                for clock in ("%I:%M %p", "%H:%M", "%H:%M:%S"):
                    try:
                        observed = datetime.strptime(normalized, date + " " + clock)
                        if observed == target.replace(tzinfo=None, second=observed.second, microsecond=0):
                            return True
                    except ValueError:
                        continue
    if amount:
        try:
            number = Decimal(field.value)
            # Receipts commonly print RM30,100.00 / INR1000 without a space.
            # Strip only known currency prefixes at a token boundary; retain
            # numeric boundaries so embedded identifiers cannot match an amount.
            money_text = re.sub(r"(?<![\w])(?:MYR|INR|SGD|RM|Rs\.?)(?=\s*\d)", " ", text, flags=re.I)
            return any(Decimal(m.replace(",", "")) == number
                       for m in re.findall(r"(?<![\w])\d[\d,]*(?:\.\d+)?(?![\w]|\.\d)", money_text))
        except InvalidOperation:
            return False
    return bool(re.search(r"(?<![\w@])" + re.escape(value) + r"(?![\w@]|\.[\w])", source))


def _check(field: Field_, pattern: str | None, what: str, texts: dict[str, str],
           *, amount: bool = False, timestamp: bool = False) -> Field_:
    if not field.value:
        field.valid, field.status, field.issue = False, "missing", f"{what} missing"
        return field
    if field.status != "user":
        sources = texts
        if field.source_file:
            # The model may echo the prompt label ("FILE <id> name.png:"); normalise it.
            named = re.sub(r"^\s*FILE\s+", "", field.source_file, flags=re.I).rstrip(": ").strip()
            if named in texts:
                sources = {named: texts[named]}
            else:
                # Accept an omitted upload prefix only when the basename is unique.
                # Labels are "<evidence id> <filename>"; the model may echo the id, the
                # filename or both.
                def basename(label):
                    return PurePath(label.split(" ", 1)[-1]).name.casefold()
                key = named.casefold()
                aliases = [label for label in texts
                           if basename(label) == basename(named) or label.split(" ", 1)[0].casefold() == key]
                sources = {aliases[0]: texts[aliases[0]]} if len(aliases) == 1 else {}
        match = next(((label, text) for label, text in sources.items()
                      if grounded(field, text, amount=amount, timestamp=timestamp)), None)
        field.status = "checked" if match else "read"
        if match:
            label, text = match
            field.source_file = label
            # Display actual independently read characters rather than the extractor's own quote.
            field.source_quote = next((line for line in text.splitlines()
                                       if grounded(field, line, amount=amount, timestamp=timestamp)), text)
    field.valid = False
    if field.issue and field.issue.startswith("Conflicting values in your screenshots:"):
        return field
    if field.status == "read":
        field.issue = f"{what} not found in independent source text - please check"
        field.confidence = min(field.confidence, .3)
        return field
    if pattern and not re.fullmatch(pattern, field.value.strip()):
        field.issue = f"{what} format looks wrong"
        field.confidence = min(field.confidence, .4)
        return field
    try:
        if amount and Decimal(field.value) <= 0:
            raise ValueError()
        if timestamp:
            dt = datetime.fromisoformat(field.value)
            if dt.tzinfo is None:
                raise ValueError()
            if dt > datetime.now(timezone.utc):
                field.issue = "Transfer date/time is in the future - please check"
                return field
    except (ValueError, InvalidOperation):
        field.issue = f"{what} must be a positive amount" if amount else "Date/time needs a real date and timezone"
        return field
    field.valid, field.issue = True, None
    return field


def is_masked_account(value: str) -> bool:
    return bool(re.search(r"[xX\*]{2,}", value or ""))


def validate_transaction(t: Transaction, country: str, texts: dict[str, str] | None = None) -> Transaction:
    texts = texts or {}
    fmt = load_pack(country)["id_formats"]
    utr_pattern = fmt["utr_upi"] if t.rail in (Rail.UPI, Rail.IMPS) else None
    if t.rail in (Rail.NEFT, Rail.RTGS):
        utr_pattern = fmt["utr_neft"]
    _check(t.utr, utr_pattern, "Transaction ID / UTR", texts)
    if t.rail == Rail.UNKNOWN:
        t.utr.valid = False
        t.utr.issue = "Payment method unknown - check the receipt before using this reference"
    _check(t.amount, r"\d+(\.\d{1,2})?", "Amount", texts, amount=True)
    _check(t.timestamp, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*", "Date/time", texts, timestamp=True)
    _check(t.victim_account_masked, None, "Your account", texts)
    b = t.beneficiary
    for field, pattern, label in ((b.vpa, fmt["vpa"], "Beneficiary UPI ID"),
                                  (b.account, fmt["account"], "Beneficiary account"),
                                  (b.ifsc, fmt["ifsc"], "IFSC"),
                                  (b.bank, None, "Beneficiary bank"), (b.name, None, "Beneficiary name")):
        _check(field, pattern, label, texts)
    if b.account.value and is_masked_account(b.account.value):
        b.account.valid = False
        b.account.issue = "Masked number - ask your bank for the full beneficiary account"
    return t


def validate_case(case: Case) -> Case:
    case.transactions = [validate_transaction(t, case.country, case.evidence_text) for t in case.transactions]
    return case


def valid_phone(value: str, country: str) -> bool:
    return bool(re.fullmatch(load_pack(country)["id_formats"]["phone"], (value or "").strip()))
