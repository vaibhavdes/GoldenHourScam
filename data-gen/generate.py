"""Synthetic scam-case generator with ground truth.

Outputs (data-gen/out/):
  cases.json            seed for the console (Case objects + _minutes_ago) + ground-truth clusters
  artifacts/<case>/...  rendered PNG screenshots + truth.json
  split.json            dev/test split (test is held out - never tune prompts on it)

Realism choices (see PLAN.md §6):
  * scam-type mix = India 2025 case shares; Malaysia cases use DuitNow + Bahasa Melayu chats
  * 6 bank SMS formats + IMPS/NEFT variants; some show only payee NAME (receipt then gives UPI ID)
  * scammers ask for round amounts; victims often pay in 2-4 escalating tranches
  * decoys in every SMS thread: OTP, balance alert, a legitimate everyday debit (must NOT be extracted)
  * mule network with heavy-tailed fan-in -> realistic multi-victim clusters
  * walkthrough case GH-CASE-SUNITA linked to 6 other victims
Everything is FICTIONAL and watermarked 'SYNTHETIC'.

Usage:
  python generate.py --cases 300 --render 0      # JSON only (fast)
  python generate.py --cases 300 --render 150    # + screenshots (pip install playwright; playwright install chromium)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker
from jinja2 import Environment, FileSystemLoader

import sms_formats as F

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
TEMPLATES = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)

random.seed(42)
Faker.seed(42)
fake_in = Faker("en_IN")
try:
    fake_my = Faker("ms_MY")
except AttributeError:  # older faker without ms_MY
    fake_my = Faker("en_US")

SCAM_MIX = [("investment", 35), ("sextortion", 19), ("phishing_otp", 14), ("task_job", 12),
            ("impersonation", 8), ("digital_arrest", 6), ("shopping", 6)]
# (min, max) TOTAL loss in INR, illustrative and right-skewed
AMOUNTS = {"investment": (25000, 1200000), "sextortion": (5000, 80000), "digital_arrest": (80000, 2500000),
           "phishing_otp": (2000, 180000), "task_job": (3000, 150000), "impersonation": (5000, 250000),
           "shopping": (499, 45000)}
TRANCHES = {"investment": [1, 2, 3, 4], "digital_arrest": [1, 2, 3], "task_job": [2, 3, 4],
            "sextortion": [1, 2], "phishing_otp": [1, 2], "impersonation": [1, 2], "shopping": [1]}
PSP = ["okaxis", "okhdfcbank", "oksbi", "ybl", "ibl", "paytm", "axl"]
BANKS_IN = {"sbi": ("State Bank of India", "SBIN"), "hdfc": ("HDFC Bank", "HDFC"),
            "icici": ("ICICI Bank", "ICIC"), "axis": ("Axis Bank", "UTIB"),
            "kotak": ("Kotak Mahindra Bank", "KKBK"), "pnb": ("Punjab National Bank", "PUNB")}
BANKS_MY = {"Maybank": "MBBEMYKL", "CIMB": "CIBBMYKL", "Public Bank": "PBBEMYKL", "RHB": "RHBBMYKL"}
CLAIMS = {"digital_arrest": ["CBI officer", "Mumbai Cyber Police", "Customs officer", "RBI vigilance cell"],
          "investment": ["SEBI-registered advisor", "VIP stock group mentor", "IPO allotment desk"],
          "task_job": ["HR, Amazon partner agency", "YouTube likes task manager"],
          "sextortion": ["Unknown video caller"], "phishing_otp": ["Electricity board", "Bank KYC desk"],
          "impersonation": ["Nephew in hospital", "Company director"], "shopping": ["Online furniture seller"]}
CLAIMS_MY = {"digital_arrest": ["Pegawai PDRM Bukit Aman", "Pegawai Bank Negara"],
             "investment": ["Mentor pelaburan saham", "Pengurus dana kripto"],
             "task_job": ["Ejen kerja sambilan"], "phishing_otp": ["Pegawai bank"], "sextortion": ["Pemanggil video"],
             "impersonation": ["Anak saudara"], "shopping": ["Penjual Facebook"]}
TZ = {"IN": timezone(timedelta(hours=5, minutes=30)), "MY": timezone(timedelta(hours=8))}
LEGIT_PAYEES = ["ZEPTO MARKETPLACE", "BIGBASKET", "SWIGGY", "BESCOM", "JIO PREPAID", "IRCTC"]


def weighted(pairs):
    r, acc = random.uniform(0, sum(w for _, w in pairs)), 0.0
    for item, w in pairs:
        acc += w
        if r <= acc:
            return item
    return pairs[-1][0]


def rrn() -> str:
    return str(random.randint(5, 6)) + "".join(random.choice("0123456789") for _ in range(11))


def neft_utr(prefix: str) -> str:
    return f"{prefix}N{random.randint(10**14, 10**15 - 1)}"


def split_amount(total: float, n: int, round_to: int) -> list[float]:
    """Escalating tranches, rounded like scammer demands (e.g. 50,000 then 1,45,000)."""
    weights = sorted(random.uniform(0.5, 1.5) for _ in range(n))
    parts = [max(round_to, round(total * w / sum(weights) / round_to) * round_to) for w in weights]
    return [float(p) for p in parts]


def field(value, quote=None, conf=0.95, file=None):
    return {"value": value, "confidence": conf, "source_quote": quote if quote is not None else value,
            "source_file": file, "valid": False}


# ------------------------------------------------------------------ mule network
def mule_network(n_l1=40):
    mules = []
    for i in range(n_l1):
        key, (name, ifsc_p) = random.choice(list(BANKS_IN.items()))
        word = random.choice(["trade", "verify", "safe", "fund", "kyc", "pay", "rbi", "secure"])
        my_bank = random.choice(list(BANKS_MY))
        mules.append({
            "id": f"M{i:02d}",
            "vpa": f"{fake_in.first_name().lower()}.{word}{random.randint(1, 99)}@{random.choice(PSP)}",
            "account": str(random.randint(10**10, 10**12 - 1)),
            "ifsc": ifsc_p + "0" + "".join(random.choice("0123456789") for _ in range(6)),
            "bank": name,
            "my_account": str(random.randint(10**11, 10**12 - 1)), "my_bank": my_bank,
            "my_name": random.choice(["SAFE CUSTODY ENT", "AMANAH DIGITAL TRADING", "GLOBAL MERIT RESOURCES",
                                      "KAYA HARTA SDN BHD"]),
            # heavy-tailed fan-in: most mules hit 1-3 victims, a few hit 10+
            "fanin": min(15, max(1, int(random.paretovariate(1.2)))) if i < 32 else 1,
        })
    return mules


# ------------------------------------------------------------------ case builders
def build_in_case(idx: int, mule: dict, scam: str | None = None, *, fixed=None, force_rail=None) -> dict:
    scam = scam or weighted(SCAM_MIX)
    lo, hi = AMOUNTS[scam]
    total = fixed["total"] if fixed else round(min(hi, lo + random.paretovariate(1.5) * lo * 0.6), -2)
    n = fixed["n"] if fixed else random.choice(TRANCHES[scam])
    round_to = 1000 if scam in ("digital_arrest", "investment", "task_job") and total > 20000 else 1
    amounts = fixed["amounts"] if fixed else split_amount(total, n, round_to)
    tz = TZ["IN"]
    start = fixed["start"] if fixed else datetime(2026, 10, 3, random.randint(8, 21), random.randint(0, 59), tzinfo=tz)
    bank_key = fixed["bank"] if fixed else random.choice(list(BANKS_IN))
    acct4 = fixed["acct4"] if fixed else f"{random.randint(1000, 9999)}"
    txns, renders, t = [], [], start
    # one rail per case (victims repeat the same method); determines which identifier they can see
    rail = force_rail or ("UPI" if fixed else random.choices(["UPI", "IMPS", "NEFT"], weights=[78, 14, 8])[0])
    for i, amt in enumerate(amounts):
        t = t + timedelta(minutes=fixed["gaps"][i] if fixed else random.randint(5, 35))
        if rail == "UPI":
            ref = rrn()
            sms, shows_vpa = F.IN_UPI[bank_key](amt, acct4, t, mule["vpa"], ref, rail)
        elif rail == "IMPS":
            ref = rrn()
            sms, shows_vpa = F.in_imps(amt, acct4, t, mule["vpa"], ref, rail, mule["account"], mule["ifsc"])
        else:
            ref = neft_utr(BANKS_IN[bank_key][1])
            sms, shows_vpa = F.in_neft(amt, acct4, t, mule["vpa"], ref, rail, mule["account"], mule["ifsc"])
        uses_vpa = rail == "UPI"
        amount_str = f"{amt:.2f}"
        ben = {"vpa": field(mule["vpa"] if uses_vpa else None, sms if shows_vpa else None),
               "account": field(None if uses_vpa else mule["account"], sms if not uses_vpa else None),
               "ifsc": field(None if uses_vpa else mule["ifsc"], sms if not uses_vpa else None),
               "bank": field(None if uses_vpa else mule["bank"]),
               "name": field(None, None, 0)}
        txns.append({"id": f"t{i + 1}", "currency": "INR", "rail": rail, "direction": "debit",
                     "amount": field(amount_str, sms), "utr": field(ref, sms),
                     "timestamp": field(t.isoformat(), None, 0.9),
                     "victim_account_masked": field(f"XX{acct4}", sms),
                     "beneficiary": ben, "confirmed": True})
        renders.append({"sms": sms, "needs_receipt": uses_vpa and (not shows_vpa or random.random() < 0.4),
                        "amount": amt, "ref": ref, "ts": t, "vpa": mule["vpa"], "rail": rail,
                        "account": mule["account"], "ifsc": mule["ifsc"]})
    claim = fixed["claim"] if fixed else random.choice(CLAIMS[scam])
    phone = fixed["phone"] if fixed else f"+91 00000{idx:05d}"
    lang = fixed["lang"] if fixed else random.choices(["en", "hi", "hinglish"], weights=[45, 35, 20])[0]
    victim = fixed["victim"] if fixed else fake_in.name()
    case = {"id": fixed["id"] if fixed else f"GH-SYN{idx:04d}", "country": "IN",
            "language": "hi" if lang == "hi" else "en",
            "victim_name": victim, "victim_age": fixed["age"] if fixed else random.randint(21, 84),
            "scam_type": scam, "scam_type_confidence": 0.9, "transactions": txns,
            "suspects": [{"phone": phone, "platform": random.choice(["WhatsApp", "Telegram", "Phone call"]),
                          "claimed_identity": claim}], "synthetic": True}
    return {"case": case, "_render": {"bank": bank_key, "acct4": acct4, "txns": renders, "claim": claim,
                                      "phone": phone, "lang": lang, "currency": "INR", "country": "IN"}}


def build_my_case(idx: int, mule: dict) -> dict:
    scam = weighted([("investment", 40), ("digital_arrest", 25), ("phishing_otp", 15), ("task_job", 12),
                     ("shopping", 8)])
    total = round(random.uniform(800, 120000), -1)
    n = random.choice([1, 2, 3])
    amounts = split_amount(total, n, 100 if total > 3000 else 1)
    start = datetime(2026, 10, 3, random.randint(8, 21), random.randint(0, 59), tzinfo=TZ["MY"])
    bank = random.choice(list(BANKS_MY))
    acct4 = f"{random.randint(1000, 9999)}"
    txns, renders, t = [], [], start
    for i, amt in enumerate(amounts):
        t = t + timedelta(minutes=random.randint(5, 40))
        ref = F.duitnow_ref(t, BANKS_MY[bank][:4])
        sms, _ = F.my_duitnow(amt, acct4, t, mule["my_name"], ref, bank)
        txns.append({"id": f"t{i + 1}", "currency": "MYR", "rail": "DUITNOW", "direction": "debit",
                     "amount": field(f"{amt:.2f}", sms), "utr": field(ref, sms),
                     "timestamp": field(t.isoformat(), None, 0.9),
                     "victim_account_masked": field(f"xxxxxx{acct4}", sms),
                     "beneficiary": {"vpa": field(None, None, 0), "account": field(mule["my_account"]),
                                     "ifsc": field(None, None, 0), "bank": field(mule["my_bank"]),
                                     "name": field(mule["my_name"], sms)},
                     "confirmed": True})
        renders.append({"sms": sms, "needs_receipt": True, "amount": amt, "ref": ref, "ts": t,
                        "vpa": None, "rail": "DuitNow", "account": mule["my_account"], "ifsc": None,
                        "name": mule["my_name"], "bank": mule["my_bank"]})
    claim = random.choice(CLAIMS_MY[scam])
    phone = f"+60 1{random.randint(1, 9)}-{random.randint(100, 999)} {random.randint(1000, 9999)}"
    case = {"id": f"GH-SYN{idx:04d}", "country": "MY", "language": "ms", "victim_name": fake_my.name(),
            "victim_age": random.randint(21, 80), "scam_type": scam, "scam_type_confidence": 0.9,
            "transactions": txns, "suspects": [{"phone": phone, "platform": "WhatsApp", "claimed_identity": claim}],
            "synthetic": True}
    return {"case": case, "_render": {"bank": bank, "acct4": acct4, "txns": renders, "claim": claim,
                                      "phone": phone, "lang": "ms", "currency": "MYR", "country": "MY"}}


def hero_case(mule: dict) -> dict:
    """Walkthrough story: Mrs. Sunita Rao, 67, Pune - digital arrest, 2 UPI transfers."""
    tz = TZ["IN"]
    return build_in_case(0, mule, "digital_arrest", fixed={
        "id": "GH-CASE-SUNITA", "total": 485000, "n": 2, "amounts": [240000.0, 245000.0],
        "start": datetime.now(tz) - timedelta(minutes=56), "gaps": [29, 13], "bank": "sbi", "acct4": "4821",
        "claim": "CBI officer (Mumbai)", "phone": "+91 0000002215", "lang": "hi",
        "victim": "Sunita Rao", "age": 67})


# ------------------------------------------------------------------ chats
def chat_messages(scam: str, claim: str, payee: str, lang: str) -> list[dict]:
    if lang == "ms":
        lib = {
            "digital_arrest": [("them", f"Saya {claim}. Akaun bank anda terlibat dalam kes pengubahan wang haram."),
                               ("them", "Jangan beritahu sesiapa. Ini siasatan sulit."),
                               ("them", f"Pindahkan semua simpanan ke akaun selamat {payee} untuk semakan."),
                               ("me", "Baik encik, saya pindahkan sekarang")],
            "investment": [("them", "Tahniah! Anda layak sertai kumpulan VIP saham kami. Untung 30% seminggu."),
                           ("them", f"Deposit ke akaun syarikat {payee}"),
                           ("them", "Untuk pengeluaran, sila bayar cukai 15% dahulu."),
                           ("me", "Bila boleh keluarkan duit saya?")],
        }
        msgs = lib.get(scam, [("them", f"Saya {claim}. Sila bayar ke {payee} segera."), ("me", "Sudah bayar.")])
    elif scam == "digital_arrest" and lang == "hi":
        msgs = [("them", f"मैं {claim} से बोल रहा हूँ। आपके नाम से मुंबई से एक पार्सल गया है जिसमें ड्रग्स और 5 नकली पासपोर्ट मिले हैं।"),
                ("them", "आप डिजिटल अरेस्ट में हैं। वीडियो कॉल मत काटिए, किसी को मत बताइए।"),
                ("them", f"अपने पैसे RBI वेरिफिकेशन खाते में भेजिए: {payee}. जाँच के बाद 2 घंटे में वापस आ जाएँगे।"),
                ("me", "ठीक है सर, भेज रही हूँ")]
    elif scam == "digital_arrest":
        msgs = [("them", f"I am {claim}. A parcel in your name has MDMA and fake passports."),
                ("them", "You are under digital arrest. Do not disconnect or tell family."),
                ("them", f"Transfer funds to RBI verification account {payee}. Refund in 2 hours."),
                ("me", "Ok sir I am sending")]
    elif scam == "investment":
        msgs = [("them", f"Welcome to VIP Alpha Traders. I am your {claim}."),
                ("them", "Today's IPO allotment gives 300% returns. Minimum 50,000."),
                ("them", f"Deposit to our settlement UPI {payee}"),
                ("them", "To withdraw profit pay 18% tax first."),
                ("me", "bhai withdrawal kab hoga? paise bhej diye" if lang == "hinglish" else "When can I withdraw?")]
    elif scam == "task_job":
        msgs = [("them", "Part time job: like YouTube videos, earn 5000/day"),
                ("them", f"Prepaid task: send 10,000 to {payee}, get 13,000 back"),
                ("me", "Done. Where is my return?"), ("them", "Complete 3 more tasks to unlock commission.")]
    elif scam == "sextortion":
        msgs = [("them", "I have recorded your video call. Pay or I send it to all your contacts."),
                ("them", f"Pay to {payee} in 30 minutes"), ("me", "Please don't. I paid.")]
    else:
        msgs = [("them", f"This is {claim}."), ("them", f"Pay now to {payee} to avoid problems."), ("me", "Paid.")]
    return [{"who": w, "text": t} for w, t in msgs]


# ------------------------------------------------------------------ rendering
async def render(items: list[dict]) -> list[str]:
    from playwright.async_api import async_playwright

    done = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        for item in items:
            c, r = item["case"], item["_render"]
            d = OUT / "artifacts" / c["id"]
            d.mkdir(parents=True, exist_ok=True)
            files = []
            sender = f"AX-{r['bank'].upper()[:6]}" if r["country"] == "IN" else r["bank"]
            for i, tx in enumerate(r["txns"], 1):
                legit_amt = random.choice([149, 236, 389, 612, 1299, 2450])
                legit = (f"Rs.{legit_amt}.00 debited from A/c XX{r['acct4']} to {random.choice(LEGIT_PAYEES)} "
                         f"UPI Ref No {rrn()}") if r["country"] == "IN" else \
                        f"RM{legit_amt / 10:.2f} paid to MYNEWS via DuitNow QR."
                html = TEMPLATES.get_template("sms.html").render(
                    sms=tx["sms"], sender=sender, dark=random.random() < 0.3,
                    decoys=c["id"] == "GH-CASE-SUNITA" or random.random() < 0.7, decoy_otp=random.randint(100000, 999999),
                    balance=f"{random.randint(1000, 900000):,}.{random.randint(10, 99)}",
                    legit=legit if c["id"] == "GH-CASE-SUNITA" or random.random() < 0.5 else None,
                    currency="Rs." if r["country"] == "IN" else "RM")
                await page.set_content(html)
                await page.screenshot(path=str(d / f"sms_{i}.png"), full_page=True)
                files.append(f"sms_{i}.png")
                if tx["needs_receipt"]:
                    html = TEMPLATES.get_template("receipt.html").render(
                        amount=tx["amount"], symbol="₹" if r["country"] == "IN" else "RM",
                        to=tx["vpa"] or tx.get("name"), ref=tx["ref"], ts=tx["ts"],
                        acct=f"XX{r['acct4']}", rail=tx["rail"], account=tx.get("account"),
                        bank=tx.get("bank"), ref_label="UPI transaction ID" if tx["rail"] == "UPI" else "Reference")
                    await page.set_content(html)
                    await page.screenshot(path=str(d / f"receipt_{i}.png"), full_page=True)
                    files.append(f"receipt_{i}.png")
            payee = r["txns"][0]["vpa"] or r["txns"][0].get("account")
            html = TEMPLATES.get_template("chat.html").render(
                name=r["claim"], phone=r["phone"], messages=chat_messages(c["scam_type"], r["claim"], payee, r["lang"]))
            await page.set_content(html)
            await page.screenshot(path=str(d / "chat.png"), full_page=True)
            files.append("chat.png")
            truth = {"case_id": c["id"], "country": c["country"], "scam_type": c["scam_type"], "files": files,
                     "transactions": [{"utr": tx["utr"]["value"], "amount": tx["amount"]["value"],
                                       "beneficiary_vpa": tx["beneficiary"]["vpa"]["value"],
                                       "beneficiary_account": tx["beneficiary"]["account"]["value"],
                                       "victim_account_masked": tx["victim_account_masked"]["value"]}
                                      for tx in c["transactions"]],
                     "suspect_phone": r["phone"]}
            (d / "truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")
            done.append(c["id"])
        await browser.close()
    return done


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--render", type=int, default=0, help="number of cases to render as screenshots")
    ap.add_argument("--my-share", type=float, default=0.15, help="share of Malaysia cases")
    ap.add_argument("--hero-only", action="store_true", help="Refresh only the five walkthrough images; leave evaluation split/seed unchanged")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args()
    OUT = args.output.resolve()
    random.seed(args.seed); Faker.seed(args.seed)
    fake_in.seed_instance(args.seed); fake_my.seed_instance(args.seed)
    if not args.hero_only and args.cases < 7:
        ap.error("At least seven cases are needed for the hero and six linked peers")
    OUT.mkdir(parents=True, exist_ok=True)

    mules = mule_network()
    hero_mule = mules[0]
    hero_mule["vpa"] = "rbi.verify.cell@oksbi"   # fictional handle for the walkthrough case
    hero_mule["fanin"] = 6                   # hero beneficiary appears in 6 other cases
    if args.hero_only:
        asyncio.run(render([hero_case(hero_mule)]))
        print("refreshed only GH-CASE-SUNITA artifacts; evaluation split and seed unchanged")
        return
    other_mules = mules[1:]
    slots = [m for m in other_mules for _ in range(m["fanin"])]
    random.shuffle(slots)

    items = [hero_case(hero_mule)]
    items[0]["_mule"] = hero_mule["id"]
    items[0]["_minutes_ago"] = 27            # walkthrough: 27 min since first transfer at recording time
    for i in range(1, args.cases):
        if i <= 6:
            mule = hero_mule
            item = build_in_case(i, mule, force_rail="UPI")
        else:
            mule = slots[i - 7] if i - 7 < len(slots) else random.choice(other_mules)
            item = build_my_case(i, mule) if random.random() < args.my_share else build_in_case(i, mule)
        item["_mule"] = mule["id"]
        item["_minutes_ago"] = random.choice([6, 12, 18, 25, 35, 48, 58, 75, 120, 240, 480, 900, 1500, 2800, 4300])
        items.append(item)

    # Linking is per identifier; India and Malaysia cases on the same mule use different identifiers,
    # so ground truth = same mule AND same country.
    # Ground truth: victims are linkable when they paid the same mule via an identifier type they can
    # see (UPI ID for UPI; account number for IMPS/NEFT/DuitNow).
    groups: dict[tuple, list[str]] = {}
    for it in items:
        rail = it["case"]["transactions"][0]["rail"]
        kind = "vpa" if rail == "UPI" else "account"
        groups.setdefault((it["_mule"], it["case"]["country"], kind), []).append(it["case"]["id"])

    seed = {"generated_at": datetime.now(timezone.utc).isoformat(), "synthetic": True,
            "cases": [{"case": it["case"], "_minutes_ago": it["_minutes_ago"]} for it in items],
            "ground_truth_clusters": [v for v in groups.values() if len(v) > 1]}
    (OUT / "cases.json").write_text(json.dumps(seed, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(items)} cases ({sum(1 for i in items if i['case']['country'] == 'MY')} MY), "
          f"{len(seed['ground_truth_clusters'])} multi-victim clusters")

    if args.render:
        to_render = items[: args.render]
        ids = asyncio.run(render(to_render))
        rest = [i for i in ids if i != "GH-CASE-SUNITA"]
        random.shuffle(rest)
        half = len(rest) // 2
        (OUT / "split.json").write_text(json.dumps({"dev": rest[:half], "test": rest[half:],
                                                    "walkthrough": ["GH-CASE-SUNITA"]}, indent=1))
        print(f"rendered {len(ids)} artifact sets -> out/artifacts/")


if __name__ == "__main__":
    main()
