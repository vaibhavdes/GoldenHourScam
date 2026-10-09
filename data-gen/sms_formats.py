"""Bank-style debit SMS formats (structure modelled on common public formats; all values fictional).

Each formatter returns (sms_text, shows_vpa). When a format shows only the payee NAME (not the
UPI ID), the renderer also produces a payment receipt so the beneficiary UPI ID is recoverable -
exactly like a real victim who has to combine the SMS with the UPI-app receipt.

Helpline numbers are random fakes on purpose (they are extraction traps, not real numbers).
"""
from __future__ import annotations

import random
from datetime import datetime


def _fake_tollfree() -> str:
    return "1800" + "".join(random.choice("0123456789") for _ in range(7))


def _fake_mobile() -> str:
    return random.choice("6789") + "".join(random.choice("0123456789") for _ in range(9))


def _payee_name(vpa: str) -> str:
    return vpa.split("@")[0].replace(".", " ").replace("_", " ").upper()[:20]


def in_sbi(amt, acct4, ts: datetime, vpa, ref, rail):
    return (f"Dear UPI user A/C X{acct4} debited by {amt:.1f} on date {ts:%d%b%y} trf to "
            f"{_payee_name(vpa)} Refno {ref}. If not u? call {_fake_tollfree()}. -SBI"), False


def in_hdfc(amt, acct4, ts, vpa, ref, rail):
    return (f"Sent Rs.{amt:.2f}\nFrom HDFC Bank A/C *{acct4}\nTo {_payee_name(vpa)}\nOn {ts:%d/%m/%y}\n"
            f"Ref {ref}\nNot You?\nCall {_fake_tollfree()}/SMS BLOCK UPI to {_fake_mobile()}"), False


def in_icici(amt, acct4, ts, vpa, ref, rail):
    return (f"ICICI Bank Acct XX{acct4[-3:]} debited for Rs {amt:.2f} on {ts:%d-%b-%y}; "
            f"{_payee_name(vpa)} credited. UPI:{ref}. Call {_fake_tollfree()} for dispute. "
            f"SMS BLOCK {acct4[-3:]} to {_fake_mobile()}."), False


def in_axis(amt, acct4, ts, vpa, ref, rail):
    return (f"INR {amt:.2f} debited\nA/c no. XX{acct4}\n{ts:%d-%m-%y, %H:%M:%S}\n"
            f"UPI/P2A/{ref}/{_payee_name(vpa)}\nNot you? SMS BLOCKUPI Cust ID to {_fake_mobile()}\nAxis Bank"), False


def in_kotak(amt, acct4, ts, vpa, ref, rail):
    return (f"Sent Rs.{amt:.2f} from Kotak Bank AC X{acct4} to {vpa} on {ts:%d-%m-%y}.UPI Ref {ref}. "
            f"Not you, call {_fake_tollfree()}"), True


def in_pnb(amt, acct4, ts, vpa, ref, rail):
    bal = random.randint(1000, 400000) + random.random()
    return (f"A/c XX{acct4} debited INR {amt:,.2f} Dt {ts:%d-%m-%y %H:%M:%S} thru UPI:{ref} to {vpa}."
            f"Bal INR {bal:,.2f} Not u?Fwd this SMS to {_fake_mobile()} to block UPI.-PNB"), True


def in_imps(amt, acct4, ts, vpa, ref, rail, acct=None, ifsc=None):
    return (f"Your A/c XX{acct4} is debited for INR {amt:,.2f} on {ts:%d-%m-%Y %H:%M} towards IMPS "
            f"to A/c XX{acct[-4:]} IFSC {ifsc}. IMPS Ref No {ref}. Not you? Call {_fake_tollfree()}"), False


def in_neft(amt, acct4, ts, vpa, ref, rail, acct=None, ifsc=None):
    return (f"NEFT of INR {amt:,.2f} from A/c XX{acct4} to A/c {acct} (IFSC {ifsc}) has been "
            f"initiated on {ts:%d-%b-%Y %H:%M}. UTR {ref}. Call {_fake_tollfree()} if not done by you."), False


IN_UPI = {"sbi": in_sbi, "hdfc": in_hdfc, "icici": in_icici, "axis": in_axis, "kotak": in_kotak, "pnb": in_pnb}


def my_duitnow(amt, acct4, ts, recipient_name, ref, bank):
    return (f"{bank}: RM{amt:,.2f} transferred from A/C xxxxxx{acct4} to {recipient_name} via DuitNow "
            f"on {ts:%d/%m/%y %H:%M}. Ref: {ref}. Not you? Call {bank} Fraud Hotline 03-{random.randint(2000, 9999)} "
            f"{random.randint(1000, 9999)} immediately."), False


def duitnow_ref(ts: datetime, bank_code: str) -> str:
    return f"{ts:%Y%m%d}{bank_code}010ORB{random.randint(10**7, 10**8 - 1)}"
