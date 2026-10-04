"""
Raqib synthetic data generator.

Builds a fully synthetic, referentially consistent dataset for a fictional UAE bank
("Gulf Horizon Bank") and plants known AML / fraud typologies so the detection layer
can be validated against ground truth (data/generated/planted_cases.csv).

No real people, accounts or institutions. Deterministic for a given --seed.

Usage:
    python data_gen/generate.py --out data/generated --seed 42
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------------------
AS_OF = date(2026, 9, 30)          # last day of the observation window
DAYS = 180                         # observation window length
START = AS_OF - timedelta(days=DAYS - 1)
BANK_CODE = "033"                  # fictional bank code used in IBANs

EMIRATES = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah", "Umm Al Quwain"]
EMIRATE_W = [0.42, 0.28, 0.14, 0.06, 0.05, 0.03, 0.02]
BRANCHES = {
    "Dubai": ["DXB-DEIRA", "DXB-BURDUBAI", "DXB-MARINA", "DXB-JLT", "DXB-KARAMA"],
    "Abu Dhabi": ["AUH-CORNICHE", "AUH-KHALIDIYA", "AUH-MUSSAFAH"],
    "Sharjah": ["SHJ-ROLLA", "SHJ-INDUSTRIAL"],
    "Ajman": ["AJM-CENTRAL"],
    "Ras Al Khaimah": ["RAK-NAKHEEL"],
    "Fujairah": ["FUJ-CITY"],
    "Umm Al Quwain": ["UAQ-CITY"],
}

# Nationality mix loosely reflecting the UAE resident population (illustrative only).
NATIONALITIES = ["AE", "IN", "PK", "EG", "PH", "BD", "GB", "JO", "LB", "SY", "SA", "US", "RU", "CN", "NG", "IR"]
NATIONALITY_W = [0.12, 0.27, 0.12, 0.07, 0.07, 0.05, 0.04, 0.03, 0.03, 0.03, 0.02, 0.02, 0.03, 0.03, 0.02, 0.05]

# Country risk is ILLUSTRATIVE and synthetic. It is not an official list.
COUNTRIES = {
    # code: (name, fatf_status, risk_tier)
    "AE": ("United Arab Emirates", "NONE", "LOW"),
    "SA": ("Saudi Arabia", "NONE", "LOW"),
    "GB": ("United Kingdom", "NONE", "LOW"),
    "US": ("United States", "NONE", "LOW"),
    "DE": ("Germany", "NONE", "LOW"),
    "SG": ("Singapore", "NONE", "LOW"),
    "IN": ("India", "NONE", "MEDIUM"),
    "PK": ("Pakistan", "NONE", "MEDIUM"),
    "EG": ("Egypt", "NONE", "MEDIUM"),
    "PH": ("Philippines", "NONE", "MEDIUM"),
    "BD": ("Bangladesh", "NONE", "MEDIUM"),
    "JO": ("Jordan", "NONE", "MEDIUM"),
    "CN": ("China", "NONE", "MEDIUM"),
    "TR": ("Turkiye", "NONE", "MEDIUM"),
    "HK": ("Hong Kong SAR", "NONE", "MEDIUM"),
    "LB": ("Lebanon", "INCREASED_MONITORING", "HIGH"),
    "SY": ("Syria", "INCREASED_MONITORING", "HIGH"),
    "NG": ("Nigeria", "INCREASED_MONITORING", "HIGH"),
    "YE": ("Yemen", "INCREASED_MONITORING", "HIGH"),
    "RU": ("Russia", "NONE", "HIGH"),
    "IR": ("Iran", "CALL_FOR_ACTION", "PROHIBITED"),
    "KP": ("North Korea", "CALL_FOR_ACTION", "PROHIBITED"),
    "MM": ("Myanmar", "CALL_FOR_ACTION", "PROHIBITED"),
}
HIGH_RISK = [c for c, v in COUNTRIES.items() if v[2] in ("HIGH", "PROHIBITED")]

# Fixed FX to AED (AED is pegged to USD at 3.6725; others are illustrative constants).
FX = {"AED": 1.0, "USD": 3.6725, "EUR": 4.00, "GBP": 4.65, "INR": 0.044, "PKR": 0.013, "SAR": 0.979}

FIRST_M = ["Mohammed", "Ahmed", "Omar", "Khalid", "Yousef", "Hamdan", "Saeed", "Rashid", "Ali", "Hassan",
           "Rajesh", "Arjun", "Vikram", "Imran", "Bilal", "Tariq", "Karim", "Mahmoud", "Jose", "Mark",
           "James", "Daniel", "Sergei", "Wei", "Chinedu", "Faisal", "Nasser", "Sami", "Ravi", "Anil"]
FIRST_F = ["Fatima", "Aisha", "Mariam", "Noura", "Hessa", "Layla", "Sara", "Huda", "Priya", "Anjali",
           "Sana", "Ayesha", "Maria", "Grace", "Emily", "Olga", "Mei", "Amina", "Reem", "Dana"]
LAST = ["Al Mansoori", "Al Hashimi", "Al Suwaidi", "Al Mazrouei", "Al Nuaimi", "Al Shamsi", "Al Falasi",
        "Al Ketbi", "Khan", "Sharma", "Patel", "Nair", "Iyer", "Qureshi", "Siddiqui", "Hussain", "Haddad",
        "Mansour", "Farouk", "Santos", "Reyes", "Smith", "Taylor", "Ivanov", "Zhang", "Okafor", "Rahman",
        "Chowdhury", "Aziz", "Saleh", "Kapoor", "Menon", "Fernandes", "Gomez", "Petrov", "Haider"]
OCCUPATIONS = ["Engineer", "Teacher", "Nurse", "Sales Executive", "Accountant", "Driver", "Doctor",
               "IT Consultant", "Construction Supervisor", "Retail Manager", "Government Employee",
               "Student", "Business Owner", "Hospitality Staff", "Real Estate Broker", "Homemaker"]
INDUSTRIES = ["General Trading", "Construction", "Real Estate", "Hospitality", "Logistics", "IT Services",
              "Healthcare", "Retail", "Precious Metals & Stones", "Auto Trading", "Consultancy",
              "Food Trading", "Manpower Supply", "Money Exchange"]
HIGH_RISK_INDUSTRIES = {"Precious Metals & Stones", "Real Estate", "Money Exchange", "General Trading", "Auto Trading"}
CO_WORDS_A = ["Gulf", "Desert", "Pearl", "Falcon", "Oasis", "Horizon", "Crescent", "Emerald", "Royal", "Star",
              "Silver", "Golden", "Blue Wave", "Sahara", "Marina", "Palm", "Summit", "Atlas", "Zenith", "Delta"]
CO_SUFFIX = ["General Trading LLC", "Trading FZE", "Contracting LLC", "Logistics FZCO", "Technical Services LLC",
             "Real Estate Brokers", "Jewellery LLC", "Auto Spare Parts Trading", "Foodstuff Trading LLC",
             "Consultancy FZ-LLC", "Hospitality Group", "Building Materials LLC"]
FOREIGN_BANKS = ["Bank of Lahore (fictional)", "Mumbai Commercial Bank (fictional)", "Nile Trust Bank (fictional)",
                 "Thames Merchant Bank (fictional)", "Levant Credit Bank (fictional)", "Lagos Union Bank (fictional)",
                 "Ural Commerce Bank (fictional)", "Shenzhen Harbour Bank (fictional)", "Anatolia Trade Bank (fictional)"]

# Synthetic watchlist (fictional entities; deliberately NOT real sanctioned names).
WATCHLIST = [
    ("WL-0001", "Al Noor Strategic Trading L.L.C", "SYNTHETIC_SANCTIONS", "IR", "Proliferation finance (fictional)"),
    ("WL-0002", "Crimson Tide Shipping Company", "SYNTHETIC_SANCTIONS", "KP", "Sanctions evasion (fictional)"),
    ("WL-0003", "Viktor Alexandrovich Morozkin", "SYNTHETIC_SANCTIONS", "RU", "Asset freeze (fictional)"),
    ("WL-0004", "Golden Crescent Exchange House", "INTERNAL_BLACKLIST", "AE", "Prior STR - exited relationship"),
    ("WL-0005", "Hamid Rezaei Tabrizi", "SYNTHETIC_SANCTIONS", "IR", "Proliferation finance (fictional)"),
    ("WL-0006", "Irrawaddy Jade Holdings", "SYNTHETIC_SANCTIONS", "MM", "Military-linked entity (fictional)"),
    ("WL-0007", "Sheikh Abdulrahman Bin Saqr Al Fictiona", "PEP", "AE", "Domestic PEP (fictional)"),
    ("WL-0008", "Black Sand Petroleum FZE", "SYNTHETIC_SANCTIONS", "YE", "Terror financing (fictional)"),
    ("WL-0009", "Oleg Nikolaevich Varenko", "SYNTHETIC_SANCTIONS", "RU", "Asset freeze (fictional)"),
    ("WL-0010", "Sunrise Bullion Traders", "INTERNAL_BLACKLIST", "AE", "Trade-based ML concern"),
]
# Near-match spellings used by planted counterparties (should fuzzy-match the list above).
WATCHLIST_VARIANTS = {
    "WL-0001": "Al-Noor Strategic Trading LLC",
    "WL-0003": "Viktor A. Morozkin",
    "WL-0006": "Irawaddy Jade Holding",
    "WL-0010": "Sunrise Bullion Trader LLC",
}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def iban(acct_num: str) -> str:
    """Build a check-digit-valid UAE-format IBAN (AEkk BBB AAAAAAAAAAAAAAAA)."""
    bban = BANK_CODE + acct_num.zfill(16)
    rearranged = bban + "AE00"
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    check = 98 - (int(numeric) % 97)
    return f"AE{check:02d}{bban}"


def emirates_id(rng: random.Random, dob: date) -> str:
    return f"784-{dob.year}-{rng.randint(1000000, 9999999)}-{rng.randint(0, 9)}"


def ts(d: date, rng: random.Random, start_h=7, end_h=22) -> datetime:
    return datetime(d.year, d.month, d.day, rng.randint(start_h, end_h - 1), rng.randint(0, 59), rng.randint(0, 59))


def rand_day(rng: random.Random, lo: date = START, hi: date = AS_OF) -> date:
    return lo + timedelta(days=rng.randint(0, (hi - lo).days))


def money(x: float) -> float:
    return round(x, 2)


@dataclass
class Gen:
    rng: random.Random
    customers: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    counterparties: list = field(default_factory=list)
    txns: list = field(default_factory=list)
    events: list = field(default_factory=list)
    loans: list = field(default_factory=list)
    planted: list = field(default_factory=list)
    _txn_seq: int = 0
    _cp_seq: int = 0
    _evt_seq: int = 0
    cp_by_name: dict = field(default_factory=dict)
    cp_country: dict = field(default_factory=dict)

    # ---- identity ---------------------------------------------------------------
    def person_name(self, gender=None):
        g = gender or self.rng.choice("MF")
        first = self.rng.choice(FIRST_M if g == "M" else FIRST_F)
        return f"{first} {self.rng.choice(LAST)}", g

    def company_name(self):
        return f"{self.rng.choice(CO_WORDS_A)} {self.rng.choice(CO_WORDS_A)} {self.rng.choice(CO_SUFFIX)}"

    def counterparty(self, name, country, cp_type, bank=None, internal_account=None):
        key = (name, country)
        if key in self.cp_by_name:
            return self.cp_by_name[key]
        self._cp_seq += 1
        cid = f"CP{self._cp_seq:06d}"
        self.counterparties.append({
            "COUNTERPARTY_ID": cid, "COUNTERPARTY_NAME": name, "COUNTERPARTY_TYPE": cp_type,
            "COUNTRY_CODE": country, "BANK_NAME": bank or ("Gulf Horizon Bank" if internal_account else
                                                           ("UAE Local Bank (fictional)" if country == "AE" else self.rng.choice(FOREIGN_BANKS))),
            "INTERNAL_ACCOUNT_ID": internal_account or "",
        })
        self.cp_by_name[key] = cid
        self.cp_country[cid] = country
        return cid

    def random_cp(self, country=None, cp_type=None):
        country = country or self.rng.choices(["AE", "IN", "PK", "GB", "EG", "PH", "SA", "CN", "US", "TR"],
                                              [0.55, 0.12, 0.07, 0.05, 0.05, 0.05, 0.04, 0.03, 0.02, 0.02])[0]
        cp_type = cp_type or self.rng.choice(["INDIVIDUAL", "COMPANY"])
        name = self.person_name()[0] if cp_type == "INDIVIDUAL" else self.company_name()
        return self.counterparty(name, country, cp_type)

    # ---- transactions -----------------------------------------------------------
    def txn(self, acct, when: datetime, direction, channel, amount_aed, cp_id="", cp_country="AE",
            currency="AED", purpose="", desc="", branch=""):
        self._txn_seq += 1
        amt_ccy = amount_aed / FX[currency]
        self.txns.append({
            "TXN_ID": f"T{self._txn_seq:08d}", "ACCOUNT_ID": acct["ACCOUNT_ID"], "TXN_TS": when.isoformat(sep=" "),
            "DIRECTION": direction, "CHANNEL": channel, "AMOUNT": money(amt_ccy), "CURRENCY": currency,
            "AMOUNT_AED": money(amount_aed), "COUNTERPARTY_ID": cp_id, "COUNTERPARTY_COUNTRY": cp_country,
            "PURPOSE_CODE": purpose, "DESCRIPTION": desc, "BRANCH_ID": branch,
        })
        return f"T{self._txn_seq:08d}"

    def event(self, cust_id, when: datetime, etype, device, ip_country="AE"):
        self._evt_seq += 1
        self.events.append({"EVENT_ID": f"E{self._evt_seq:08d}", "CUSTOMER_ID": cust_id,
                            "EVENT_TS": when.isoformat(sep=" "), "EVENT_TYPE": etype,
                            "DEVICE_ID": device, "IP_COUNTRY": ip_country})

    # ---- planting -----------------------------------------------------------------
    def plant(self, typology, cust, acct, rule, narrative, txn_ids):
        self.planted.append({"SCENARIO_ID": f"PC{len(self.planted) + 1:03d}", "TYPOLOGY": typology,
                             "CUSTOMER_ID": cust["CUSTOMER_ID"], "ACCOUNT_ID": acct["ACCOUNT_ID"],
                             "EXPECTED_RULE": rule, "NARRATIVE": narrative, "TXN_COUNT": len(txn_ids)})


# --------------------------------------------------------------------------------------
# Population
# --------------------------------------------------------------------------------------
def build_population(g: Gen, n_ind: int, n_corp: int):
    rng = g.rng
    acct_seq = 0

    def new_account(cust, acct_type, open_date, status="ACTIVE", currency="AED", last_activity=None):
        nonlocal acct_seq
        acct_seq += 1
        num = f"{acct_seq:010d}"
        emirate = cust["EMIRATE"]
        a = {
            "ACCOUNT_ID": f"A{acct_seq:07d}", "CUSTOMER_ID": cust["CUSTOMER_ID"], "IBAN": iban(num),
            "ACCOUNT_TYPE": acct_type, "CURRENCY": currency, "OPEN_DATE": open_date.isoformat(),
            "STATUS": status, "HOME_BRANCH": rng.choice(BRANCHES[emirate]),
            "LAST_ACTIVITY_BEFORE_WINDOW": (last_activity or (START - timedelta(days=rng.randint(1, 20)))).isoformat(),
        }
        g.accounts.append(a)
        return a

    for i in range(n_ind + n_corp):
        is_corp = i >= n_ind
        cid = f"C{i + 1:06d}"
        emirate = rng.choices(EMIRATES, EMIRATE_W)[0]
        onboard = START - timedelta(days=rng.randint(30, 365 * 12))
        if is_corp:
            name = g.company_name()
            industry = rng.choice(INDUSTRIES)
            segment = rng.choices(["SME", "CORPORATE"], [0.75, 0.25])[0]
            expected = rng.choice([150_000, 300_000, 600_000, 1_200_000, 3_000_000]) * (3 if segment == "CORPORATE" else 1)
            nationality, gender, dob, occupation = "AE", "", None, ""
        else:
            name, gender = g.person_name()
            nationality = rng.choices(NATIONALITIES, NATIONALITY_W)[0]
            dob = date(rng.randint(1958, 2004), rng.randint(1, 12), rng.randint(1, 28))
            occupation = rng.choice(OCCUPATIONS)
            industry = ""
            segment = rng.choices(["RETAIL", "PRIORITY"], [0.85, 0.15])[0]
            expected = rng.choice([8_000, 12_000, 18_000, 25_000, 40_000]) * (4 if segment == "PRIORITY" else 1)
        pep = rng.random() < 0.012
        base_risk = "HIGH" if (pep or industry in HIGH_RISK_INDUSTRIES and rng.random() < 0.35
                               or COUNTRIES.get(nationality, ("", "", "LOW"))[2] in ("HIGH", "PROHIBITED")) else \
            rng.choices(["LOW", "MEDIUM"], [0.7, 0.3])[0]
        cust = {
            "CUSTOMER_ID": cid, "FULL_NAME": name, "CUSTOMER_TYPE": "CORPORATE" if is_corp else "INDIVIDUAL",
            "SEGMENT": segment, "NATIONALITY": nationality, "RESIDENCE_COUNTRY": "AE", "EMIRATE": emirate,
            "OCCUPATION": occupation, "INDUSTRY": industry, "GENDER": gender,
            "DATE_OF_BIRTH": dob.isoformat() if dob else "",
            "EMIRATES_ID": emirates_id(rng, dob) if dob else "",
            "TRADE_LICENSE_NO": f"TL-{rng.randint(100000, 999999)}" if is_corp else "",
            "ONBOARDING_DATE": onboard.isoformat(), "KYC_RISK_RATING": base_risk, "PEP_FLAG": pep,
            "EXPECTED_MONTHLY_TURNOVER_AED": expected,
            "LAST_KYC_REVIEW_DATE": (AS_OF - timedelta(days=rng.randint(10, 900))).isoformat(),
            "PHONE": f"+9715{rng.randint(0, 8)}{rng.randint(1000000, 9999999)}",
            "EMAIL": f"{name.split()[0].lower()}.{cid.lower()}@example.ae",
        }
        g.customers.append(cust)
        new_account(cust, "BUSINESS" if is_corp else "CURRENT", onboard)
        if not is_corp and rng.random() < 0.3:
            new_account(cust, "SAVINGS", onboard + timedelta(days=rng.randint(0, 400)))
        if is_corp and rng.random() < 0.25:
            new_account(cust, "BUSINESS", onboard, currency="USD")
    return new_account


def background_activity(g: Gen):
    """Normal, mostly benign behaviour. Generates the bulk of the transaction volume."""
    rng = g.rng
    cust_by_id = {c["CUSTOMER_ID"]: c for c in g.customers}
    employers = [g.counterparty(g.company_name(), "AE", "COMPANY") for _ in range(120)]
    merchants = [g.counterparty(f"{rng.choice(CO_WORDS_A)} {s}", "AE", "COMPANY")
                 for s in ["Supermarket", "Pharmacy", "Electronics", "Fuel Station", "Restaurant", "Telecom",
                           "Utilities (DEWA-like)", "School Fees", "Clinic", "Fashion"] for _ in range(4)]
    for a in g.accounts:
        c = cust_by_id[a["CUSTOMER_ID"]]
        exp = c["EXPECTED_MONTHLY_TURNOVER_AED"]
        devices = [f"DEV-{c['CUSTOMER_ID']}-{k}" for k in range(rng.randint(1, 2))]
        # digital logins (benign)
        for _ in range(rng.randint(8, 40)):
            g.event(c["CUSTOMER_ID"], ts(rand_day(rng), rng, 6, 24), "LOGIN", rng.choice(devices), "AE")
        if a["ACCOUNT_TYPE"] in ("CURRENT", "BUSINESS") and a["CURRENCY"] == "AED" and rng.random() < 0.18:
            # benign: customer changes phone and/or adds a beneficiary from home, then pays them
            d = rand_day(rng)
            t0 = ts(d, rng, 8, 21)
            dev = rng.choice(devices)
            if rng.random() < 0.4:
                dev = f"DEV-{c['CUSTOMER_ID']}-NEW"
                g.event(c["CUSTOMER_ID"], t0 - timedelta(minutes=20), "NEW_DEVICE", dev, "AE")
            g.event(c["CUSTOMER_ID"], t0, "BENEFICIARY_ADDED", dev, "AE")
            g.txn(a, t0 + timedelta(minutes=rng.randint(5, 90)), "DEBIT", "INTERNAL_TRANSFER",
                  rng.uniform(500, 60_000), g.random_cp("AE", "INDIVIDUAL"), "AE", desc="Online transfer")
        if a["ACCOUNT_TYPE"] in ("CURRENT", "BUSINESS") and rng.random() < 0.03:
            # benign: forgot password while travelling
            g.event(c["CUSTOMER_ID"], ts(rand_day(rng), rng, 6, 23), "PASSWORD_RESET", devices[0],
                    rng.choice(["AE", "GB", "IN", "SA"]))
        if a["CURRENCY"] == "USD" or a["ACCOUNT_TYPE"] == "SAVINGS":
            # low-activity secondary accounts
            for _ in range(rng.randint(2, 10)):
                d = rand_day(rng)
                amt = exp * rng.uniform(0.05, 0.3)
                if rng.random() < 0.5:
                    g.txn(a, ts(d, rng), "CREDIT", "INTERNAL_TRANSFER", amt, desc="Transfer from own account")
                else:
                    g.txn(a, ts(d, rng), "DEBIT", "INTERNAL_TRANSFER", amt, desc="Transfer to own account")
            continue
        if c["CUSTOMER_TYPE"] == "INDIVIDUAL":
            salary = exp * rng.uniform(0.7, 0.95)
            employer = rng.choice(employers)
            pay_day = rng.randint(25, 28)
            m = date(START.year, START.month, 1)
            while m <= AS_OF:
                d = date(m.year, m.month, min(pay_day, 28))
                if START <= d <= AS_OF and c["OCCUPATION"] not in ("Student", "Homemaker"):
                    g.txn(a, ts(d, rng, 8, 11), "CREDIT", "SALARY", salary * rng.uniform(0.98, 1.02), employer, "AE",
                          purpose="SAL", desc="Payroll WPS")
                    # remittance home for expats
                    if c["NATIONALITY"] not in ("AE", "GB", "US") and rng.random() < 0.65:
                        home = c["NATIONALITY"] if c["NATIONALITY"] in COUNTRIES else "IN"
                        if COUNTRIES[home][2] in ("HIGH", "PROHIBITED"):
                            # realistic: remittances to restricted corridors go via licensed exchange houses
                            cp = g.counterparty(f"{rng.choice(CO_WORDS_A)} Exchange LLC", "AE", "COMPANY")
                        else:
                            cp = g.counterparty(g.person_name()[0], home, "INDIVIDUAL")
                        g.txn(a, ts(d + timedelta(days=rng.randint(1, 4)), rng), "DEBIT", "WIRE_OUT",
                              salary * rng.uniform(0.15, 0.4), cp, _cp_country(g, cp),
                              purpose="FAM", desc="Family support remittance")
                m = (m.replace(day=1) + timedelta(days=32)).replace(day=1)
            n_pos = int(rng.uniform(4, 14) * DAYS / 30)
            for _ in range(n_pos):
                g.txn(a, ts(rand_day(rng), rng), "DEBIT", "CARD_POS", rng.lognormvariate(math.log(180), 0.9),
                      rng.choice(merchants), "AE", desc="Card purchase")
            for _ in range(int(rng.uniform(1, 4) * DAYS / 30)):
                g.txn(a, ts(rand_day(rng), rng), "DEBIT", "ATM", rng.choice([200, 300, 500, 1000, 1500, 2000]),
                      desc="ATM withdrawal", branch=a["HOME_BRANCH"])
            # occasional benign cash deposit (varied amounts, mostly small)
            for _ in range(rng.randint(0, 3)):
                g.txn(a, ts(rand_day(rng), rng, 9, 17), "CREDIT", "CASH_DEPOSIT",
                      round(exp * rng.uniform(0.05, 0.9), -2),
                      desc="Cash deposit", branch=a["HOME_BRANCH"])
            for _ in range(rng.randint(0, 4)):
                g.txn(a, ts(rand_day(rng), rng), "DEBIT", "INTERNAL_TRANSFER", rng.uniform(200, 5000),
                      g.random_cp("AE", "INDIVIDUAL"), "AE", desc="Transfer to friend")
        else:
            # corporate: customer receipts, supplier payments, payroll, some cross-border trade
            months = DAYS / 30
            n_in = int(rng.uniform(6, 25) * months)
            n_out = int(rng.uniform(6, 25) * months)
            customers_pool = [g.random_cp(None, "COMPANY") for _ in range(rng.randint(5, 25))]
            suppliers_pool = [g.random_cp(None, "COMPANY") for _ in range(rng.randint(4, 15))]
            avg_in = exp / max(n_in / months, 1)
            for _ in range(n_in):
                cp = rng.choice(customers_pool)
                g.txn(a, ts(rand_day(rng), rng, 8, 18), "CREDIT", rng.choice(["WIRE_IN", "WIRE_IN", "CHEQUE", "INTERNAL_TRANSFER"]),
                      avg_in * rng.uniform(0.4, 1.6), cp, _cp_country(g, cp), purpose="GDS", desc="Customer payment")
            avg_out = exp * 0.85 / max(n_out / months, 1)
            for _ in range(n_out):
                cp = rng.choice(suppliers_pool)
                g.txn(a, ts(rand_day(rng), rng, 8, 18), "DEBIT", rng.choice(["WIRE_OUT", "WIRE_OUT", "INTERNAL_TRANSFER"]),
                      avg_out * rng.uniform(0.4, 1.6), cp, _cp_country(g, cp), purpose="GDS", desc="Supplier payment")
            m = date(START.year, START.month, 1)
            while m <= AS_OF:
                d = date(m.year, m.month, 27)
                if START <= d <= AS_OF:
                    g.txn(a, ts(d, rng, 8, 10), "DEBIT", "PAYROLL", exp * rng.uniform(0.15, 0.25), desc="WPS payroll run")
                m = (m.replace(day=1) + timedelta(days=32)).replace(day=1)


def _cp_country(g: Gen, cp_id: str) -> str:
    return g.cp_country[cp_id]


# --------------------------------------------------------------------------------------
# Planted typologies (ground truth)
# --------------------------------------------------------------------------------------
def pick(g: Gen, n, pred, used):
    pool = [c for c in g.customers if pred(c) and c["CUSTOMER_ID"] not in used]
    chosen = g.rng.sample(pool, n)
    used.update(c["CUSTOMER_ID"] for c in chosen)
    return chosen


def primary_account(g: Gen, cust):
    return next(a for a in g.accounts if a["CUSTOMER_ID"] == cust["CUSTOMER_ID"] and a["CURRENCY"] == "AED"
                and a["ACCOUNT_TYPE"] in ("CURRENT", "BUSINESS"))


def plant_typologies(g: Gen, new_account):
    rng = g.rng
    used: set = set()
    ind = lambda c: c["CUSTOMER_TYPE"] == "INDIVIDUAL" and c["OCCUPATION"] not in ("Student",)
    corp = lambda c: c["CUSTOMER_TYPE"] == "CORPORATE"

    # TM-01 Structuring: repeated cash deposits just under the AED 55,000 reporting threshold.
    for c in pick(g, 7, ind, used):
        a = primary_account(g, c)
        d0 = rand_day(rng, START + timedelta(days=20), AS_OF - timedelta(days=10))
        ids = []
        branches = rng.sample(sum(BRANCHES.values(), []), 5)
        for k in range(rng.randint(4, 6)):
            d = d0 + timedelta(days=rng.randint(0, 6))
            ids.append(g.txn(a, ts(d, rng, 9, 17), "CREDIT", "CASH_DEPOSIT", rng.uniform(45_500, 54_900),
                             desc="Cash deposit", branch=branches[k % len(branches)]))
        # proceeds moved out shortly after
        cp = g.random_cp(rng.choice(["TR", "HK", "PK"]), "COMPANY")
        ids.append(g.txn(a, ts(d0 + timedelta(days=8), rng), "DEBIT", "WIRE_OUT", 180_000 * rng.uniform(0.9, 1.3),
                         cp, _cp_country(g, cp), purpose="GDS", desc="Payment for goods"))
        g.plant("STRUCTURING", c, a, "TM-01",
                "Multiple cash deposits just below AED 55,000 across different branches within 7 days, followed by an outbound wire.",
                ids)

    # TM-02 Rapid pass-through / layering via corporate accounts.
    shell_like = lambda x: corp(x) and x["SEGMENT"] == "SME" and x["EXPECTED_MONTHLY_TURNOVER_AED"] <= 300_000
    for c in pick(g, 5, shell_like, used):
        # shell-like trading company: low declared turnover, large flows
        c["INDUSTRY"] = "General Trading"
        a = primary_account(g, c)
        ids = []
        n_ep = rng.randint(2, 3)
        span = (AS_OF - timedelta(days=5) - (START + timedelta(days=10))).days
        for ep in range(n_ep):
            # episodes spaced apart so each 48h window contains only its own legs
            d = START + timedelta(days=10 + ep * span // n_ep + rng.randint(0, span // n_ep - 4))
            amt = rng.uniform(400_000, 2_200_000)
            src_c = rng.choice(["HK", "TR", "RU", "CN"])
            cp_in = g.random_cp(src_c, "COMPANY")
            ids.append(g.txn(a, ts(d, rng, 8, 12), "CREDIT", "WIRE_IN", amt, cp_in, src_c, "USD", "GDS",
                             "Trade receipt - invoice"))
            forwarded = amt * rng.uniform(0.93, 0.99)
            n_parts = rng.randint(2, 4)
            weights = [rng.uniform(0.5, 1.5) for _ in range(n_parts)]
            for part in range(n_parts):
                share = forwarded * weights[part] / sum(weights)
                dst_c = rng.choice(["AE", "LB", "NG", "HK", "GB", "SY"]) if part else rng.choice(["LB", "NG", "HK", "SY"])
                cp_out = g.random_cp(dst_c, "COMPANY")
                ids.append(g.txn(a, ts(d + timedelta(days=rng.randint(0, 1)), rng, 12, 20), "DEBIT", "WIRE_OUT",
                                 share, cp_out, dst_c, "USD", "GDS", "Supplier payment"))
        g.plant("RAPID_PASS_THROUGH", c, a, "TM-02",
                "Large inbound USD wires forwarded >90% to multiple jurisdictions within 48 hours; account used as a conduit.",
                ids)

    # TM-03 Money-mule fan-in network: new individual accounts receive from many unrelated senders,
    # then forward to a common collector.
    collector = pick(g, 1, ind, used)[0]
    col_acct = primary_account(g, collector)
    col_cp = g.counterparty(collector["FULL_NAME"], "AE", "INDIVIDUAL", internal_account=col_acct["ACCOUNT_ID"])
    mule_ids_all = []
    for k in range(5):
        c = pick(g, 1, lambda x: x["CUSTOMER_TYPE"] == "INDIVIDUAL", used)[0]
        c["OCCUPATION"] = "Student"
        c["ONBOARDING_DATE"] = (AS_OF - timedelta(days=rng.randint(30, 75))).isoformat()
        c["DATE_OF_BIRTH"] = date(rng.randint(2001, 2006), rng.randint(1, 12), rng.randint(1, 28)).isoformat()
        c["EXPECTED_MONTHLY_TURNOVER_AED"] = 5_000
        a = primary_account(g, c)
        a["OPEN_DATE"] = c["ONBOARDING_DATE"]
        d0 = rand_day(rng, date.fromisoformat(a["OPEN_DATE"]) + timedelta(days=5), AS_OF - timedelta(days=8))
        ids = []
        total = 0
        for _ in range(rng.randint(12, 22)):
            cp = g.random_cp("AE", "INDIVIDUAL")
            amt = rng.uniform(2_000, 9_500)
            total += amt
            ids.append(g.txn(a, ts(d0 + timedelta(days=rng.randint(0, 4)), rng), "CREDIT", "INTERNAL_TRANSFER", amt,
                             cp, "AE", desc=rng.choice(["Rent share", "Loan repayment", "Gift", "Payment"])))
        out_id = g.txn(a, ts(d0 + timedelta(days=5), rng), "DEBIT", "INTERNAL_TRANSFER", total * 0.9, col_cp, "AE",
                       desc="Transfer")
        g.txn(col_acct, ts(d0 + timedelta(days=5), rng), "CREDIT", "INTERNAL_TRANSFER", total * 0.9,
              g.counterparty(c["FULL_NAME"], "AE", "INDIVIDUAL", internal_account=a["ACCOUNT_ID"]), "AE", desc="Transfer")
        ids.append(out_id)
        mule_ids_all += ids
        g.plant("MONEY_MULE_FAN_IN", c, a, "TM-03",
                f"Newly onboarded student account received funds from many unrelated senders in 5 days, then forwarded ~90% to {collector['CUSTOMER_ID']}.",
                ids)
    # collector cashes out abroad
    cp = g.random_cp("NG", "INDIVIDUAL")
    g.txn(col_acct, ts(AS_OF - timedelta(days=2), rng), "DEBIT", "WIRE_OUT", 250_000, cp, "NG", desc="Business investment")
    g.plant("MONEY_MULE_COLLECTOR", collector, col_acct, "TM-04",
            "Collector account aggregating funds from 5 mule accounts and wiring proceeds to a high-risk jurisdiction.", [])

    # TM-04 High-risk / prohibited jurisdiction exposure.
    for c in pick(g, 6, lambda x: True, used):
        a = primary_account(g, c)
        ids = []
        for _ in range(rng.randint(2, 4)):
            ctry = rng.choice(["IR", "SY", "MM", "YE", "LB"])
            cp = g.random_cp(ctry, "COMPANY")
            ids.append(g.txn(a, ts(rand_day(rng, START + timedelta(days=30)), rng, 9, 17), "DEBIT",
                             "WIRE_OUT",
                             rng.uniform(40_000, 350_000), cp, ctry, "USD", "GDS", "Trade settlement"))
        g.plant("HIGH_RISK_JURISDICTION", c, a, "TM-04",
                "Repeated cross-border wires to counterparties in high-risk / call-for-action jurisdictions.", ids)

    # TM-06 Watchlist (fuzzy name) hits on counterparties.
    for wl_id, variant in WATCHLIST_VARIANTS.items():
        c = pick(g, 1, corp, used)[0]
        a = primary_account(g, c)
        wl = next(w for w in WATCHLIST if w[0] == wl_id)
        cp = g.counterparty(variant, wl[3] if wl[3] != "AE" else "AE", "COMPANY" if "LLC" in variant or "Hold" in variant else "INDIVIDUAL")
        ids = [g.txn(a, ts(rand_day(rng, START + timedelta(days=15)), rng, 9, 17), "DEBIT", "WIRE_OUT",
                     rng.uniform(60_000, 480_000), cp, _cp_country(g, cp), "USD", "GDS", "Commercial payment")
               for _ in range(rng.randint(1, 3))]
        g.plant("WATCHLIST_MATCH", c, a, "TM-06",
                f"Payments to counterparty '{variant}' which closely matches watchlist entry {wl_id} ('{wl[1]}').", ids)

    # TM-05 Dormant account reactivation.
    for c in pick(g, 4, ind, used):
        a = primary_account(g, c)
        a["LAST_ACTIVITY_BEFORE_WINDOW"] = (START - timedelta(days=rng.randint(220, 500))).isoformat()
        # remove background activity for this account to make it truly dormant until reactivation
        g.txns = [t for t in g.txns if t["ACCOUNT_ID"] != a["ACCOUNT_ID"]]
        d0 = rand_day(rng, AS_OF - timedelta(days=45), AS_OF - timedelta(days=10))
        ids = []
        for _ in range(rng.randint(3, 5)):
            cp = g.random_cp(rng.choice(["AE", "TR", "HK"]), "COMPANY")
            ids.append(g.txn(a, ts(d0 + timedelta(days=rng.randint(0, 6)), rng), "CREDIT", "WIRE_IN",
                             rng.uniform(40_000, 120_000), cp, _cp_country(g, cp), desc="Consulting fee"))
        ids.append(g.txn(a, ts(d0 + timedelta(days=9), rng), "DEBIT", "CASH_WITHDRAWAL", rng.uniform(150_000, 250_000),
                         desc="Cash withdrawal - branch", branch=a["HOME_BRANCH"]))
        g.plant("DORMANT_REACTIVATION", c, a, "TM-05",
                "Account dormant for 7+ months suddenly receives large third-party credits followed by a large cash withdrawal.", ids)

    # TM-07 Activity inconsistent with declared profile.
    for c in pick(g, 5, ind, used):
        a = primary_account(g, c)
        mult = rng.uniform(6, 11)
        month_start = rand_day(rng, START + timedelta(days=30), AS_OF - timedelta(days=35))
        ids = []
        for _ in range(rng.randint(5, 9)):
            cp = g.random_cp(rng.choice(["AE", "IN", "GB"]), "COMPANY")
            ids.append(g.txn(a, ts(month_start + timedelta(days=rng.randint(0, 25)), rng), "CREDIT", "WIRE_IN",
                             c["EXPECTED_MONTHLY_TURNOVER_AED"] * mult / 7, cp, _cp_country(g, cp), desc="Commission"))
        g.plant("PROFILE_DEVIATION", c, a, "TM-07",
                f"Monthly credits ~{mult:.0f}x the declared expected turnover of AED {c['EXPECTED_MONTHLY_TURNOVER_AED']:,}.", ids)

    # FR-01 Account takeover fraud: new device + foreign IP + password reset + beneficiary added + large transfer.
    for c in pick(g, 4, lambda x: x["CUSTOMER_TYPE"] == "INDIVIDUAL" and x["SEGMENT"] == "PRIORITY", used):
        a = primary_account(g, c)
        d = rand_day(rng, AS_OF - timedelta(days=40), AS_OF - timedelta(days=1))
        t0 = datetime(d.year, d.month, d.day, rng.randint(1, 4), rng.randint(0, 59))
        dev = f"DEV-UNSEEN-{rng.randint(1000, 9999)}"
        ip = rng.choice(["NG", "RU", "VN", "BR"])
        g.event(c["CUSTOMER_ID"], t0, "OTP_FAILED", dev, ip)
        g.event(c["CUSTOMER_ID"], t0 + timedelta(minutes=3), "PASSWORD_RESET", dev, ip)
        g.event(c["CUSTOMER_ID"], t0 + timedelta(minutes=5), "NEW_DEVICE", dev, ip)
        g.event(c["CUSTOMER_ID"], t0 + timedelta(minutes=9), "BENEFICIARY_ADDED", dev, ip)
        cp = g.random_cp(rng.choice(["AE", "HK"]), "INDIVIDUAL")
        ids = [g.txn(a, t0 + timedelta(minutes=14 + 7 * k), "DEBIT", "INTERNAL_TRANSFER" if _cp_country(g, cp) == "AE" else "WIRE_OUT",
                     rng.uniform(25_000, 70_000), cp, _cp_country(g, cp), desc="Online transfer") for k in range(rng.randint(2, 3))]
        g.plant("ACCOUNT_TAKEOVER", c, a, "FR-01",
                "Failed OTP, password reset and new-device login from a foreign IP at night, new beneficiary added and drained within 30 minutes.",
                ids)

    # Showcase: one customer combining several red flags (the 'hero' case for the demo).
    hero = pick(g, 1, lambda x: x["CUSTOMER_TYPE"] == "INDIVIDUAL" and x["NATIONALITY"] not in ("AE",), used)[0]
    hero.update({"FULL_NAME": "Tariq Mahmoud Haddad", "OCCUPATION": "Real Estate Broker", "PEP_FLAG": False,
                 "EXPECTED_MONTHLY_TURNOVER_AED": 25_000, "KYC_RISK_RATING": "HIGH", "NATIONALITY": "LB",
                 "LAST_KYC_REVIEW_DATE": (AS_OF - timedelta(days=640)).isoformat()})
    ha = primary_account(g, hero)
    ids = []
    d0 = AS_OF - timedelta(days=21)
    for k in range(5):
        ids.append(g.txn(ha, ts(d0 + timedelta(days=k), rng, 9, 16), "CREDIT", "CASH_DEPOSIT", rng.uniform(49_000, 54_800),
                         desc="Cash deposit", branch=["DXB-DEIRA", "DXB-KARAMA", "SHJ-ROLLA", "AJM-CENTRAL", "DXB-BURDUBAI"][k]))
    for k in range(3):
        cp = g.counterparty(["Golden Crescent Exchange", "Cedar Line Trading SARL", "Al-Noor Strategic Trading LLC"][k],
                            ["AE", "LB", "IR"][k], "COMPANY")
        ids.append(g.txn(ha, ts(d0 + timedelta(days=6 + k), rng, 10, 15), "DEBIT", "WIRE_OUT", rng.uniform(70_000, 95_000),
                         cp, _cp_country(g, cp), "USD", "GDS", "Property deposit"))
    g.plant("MULTI_TYPOLOGY_HERO", hero, ha, "TM-01|TM-04|TM-06|TM-07",
            "Broker structures ~AED 260k cash across 5 branches in 5 days and wires it to an exchange house, a Lebanese trader and a watchlist near-match in Iran.",
            ids)


# --------------------------------------------------------------------------------------
# Credit & liquidity
# --------------------------------------------------------------------------------------
def build_loans(g: Gen):
    rng = g.rng
    n = 0
    for c in g.customers:
        if rng.random() > (0.45 if c["CUSTOMER_TYPE"] == "INDIVIDUAL" else 0.6):
            continue
        prods = (["PERSONAL", "AUTO", "MORTGAGE", "CREDIT_CARD"] if c["CUSTOMER_TYPE"] == "INDIVIDUAL"
                 else ["SME_TERM", "TRADE_FINANCE", "WORKING_CAPITAL"])
        prod = rng.choice(prods)
        base = {"PERSONAL": 120_000, "AUTO": 90_000, "MORTGAGE": 1_400_000, "CREDIT_CARD": 30_000,
                "SME_TERM": 900_000, "TRADE_FINANCE": 2_500_000, "WORKING_CAPITAL": 1_500_000}[prod]
        principal = base * rng.uniform(0.4, 1.8)
        orig = START - timedelta(days=rng.randint(30, 2000))
        outstanding = principal * rng.uniform(0.2, 0.98)
        # DPD distribution; higher-risk sectors skew worse
        risky = c["INDUSTRY"] in ("Construction", "Real Estate", "Hospitality") or c["KYC_RISK_RATING"] == "HIGH"
        r = rng.random()
        dpd = 0 if r < (0.87 if not risky else 0.70) else rng.choice([5, 12, 25, 35, 48, 62, 75, 95, 120, 181, 240])
        stage = 1 if dpd <= 30 else (2 if dpd <= 90 else 3)
        if stage == 1 and rng.random() < 0.04:
            stage = 2  # significant increase in credit risk (qualitative SICR)
        pd12 = {1: rng.uniform(0.003, 0.03), 2: rng.uniform(0.08, 0.30), 3: 1.0}[stage]
        collateral = {"MORTGAGE": principal * rng.uniform(1.1, 1.6), "AUTO": principal * rng.uniform(0.6, 1.0),
                      "TRADE_FINANCE": principal * rng.uniform(0.2, 0.8)}.get(prod, 0)
        lgd = max(0.1, min(0.75, 1 - collateral * 0.7 / max(outstanding, 1))) if collateral else rng.uniform(0.45, 0.75)
        n += 1
        g.loans.append({
            "LOAN_ID": f"L{n:06d}", "CUSTOMER_ID": c["CUSTOMER_ID"], "PRODUCT": prod,
            "SECTOR": c["INDUSTRY"] or "Retail Individual", "ORIGINATION_DATE": orig.isoformat(),
            "MATURITY_DATE": (orig + timedelta(days=rng.choice([365, 730, 1095, 1825, 7300]))).isoformat(),
            "PRINCIPAL_AED": money(principal), "OUTSTANDING_AED": money(outstanding),
            "INTEREST_RATE": round(rng.uniform(0.045, 0.16), 4), "DAYS_PAST_DUE": dpd, "IFRS9_STAGE": stage,
            "PD_12M": round(pd12, 4), "LGD": round(lgd, 4), "COLLATERAL_VALUE_AED": money(collateral),
            "AS_OF_DATE": AS_OF.isoformat(),
        })


def build_liquidity(rng: random.Random):
    """Daily LCR inputs (AED millions). Includes a stress dip around a large wholesale outflow."""
    rows = []
    l1, l2a, l2b = 7_000.0, 2_100.0, 700.0
    stable, less_stable, oper, nonoper, fin, facilities, inflows = 18_000.0, 9_500.0, 6_200.0, 7_800.0, 1_900.0, 4_200.0, 2_400.0
    for i in range(DAYS):
        d = START + timedelta(days=i)
        drift = lambda x, s=0.004: x * (1 + rng.gauss(0, s))
        l1, l2a, l2b = drift(l1), drift(l2a), drift(l2b)
        stable, less_stable, oper, nonoper = drift(stable, 0.002), drift(less_stable, 0.003), drift(oper), drift(nonoper, 0.006)
        fin, facilities, inflows = drift(fin, 0.01), drift(facilities, 0.004), drift(inflows, 0.01)
        stress = 0.0
        days_to_stress = (d - (AS_OF - timedelta(days=17))).days
        if 0 <= days_to_stress <= 6:  # large corporate deposit withdrawal drains HQLA for a week
            stress = [700, 1150, 1500, 1650, 1350, 900, 400][days_to_stress]
        rows.append({
            "AS_OF_DATE": d.isoformat(), "HQLA_LEVEL1_AED_M": round(l1 - stress, 1), "HQLA_LEVEL2A_AED_M": round(l2a, 1),
            "HQLA_LEVEL2B_AED_M": round(l2b, 1), "RETAIL_STABLE_DEPOSITS_AED_M": round(stable, 1),
            "RETAIL_LESS_STABLE_DEPOSITS_AED_M": round(less_stable, 1),
            "WHOLESALE_OPERATIONAL_AED_M": round(oper, 1),
            "WHOLESALE_NONOPERATIONAL_AED_M": round(nonoper + stress * 0.6, 1),
            "FINANCIAL_INSTITUTION_FUNDING_AED_M": round(fin, 1),
            "COMMITTED_FACILITIES_AED_M": round(facilities, 1), "CONTRACTUAL_INFLOWS_30D_AED_M": round(inflows, 1),
        })
    return rows


# --------------------------------------------------------------------------------------
def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/generated")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--individuals", type=int, default=1800)
    ap.add_argument("--corporates", type=int, default=350)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    g = Gen(random.Random(args.seed))
    new_account = build_population(g, args.individuals, args.corporates)
    background_activity(g)
    plant_typologies(g, new_account)
    build_loans(g)
    liquidity = build_liquidity(g.rng)

    g.txns.sort(key=lambda t: t["TXN_TS"])
    country_rows = [{"COUNTRY_CODE": k, "COUNTRY_NAME": v[0], "FATF_STATUS": v[1], "RISK_TIER": v[2]}
                    for k, v in COUNTRIES.items()]
    watch_rows = [{"ENTRY_ID": w[0], "ENTRY_NAME": w[1], "LIST_SOURCE": w[2], "COUNTRY_CODE": w[3], "PROGRAM": w[4]}
                  for w in WATCHLIST]

    tables = {
        "customers": g.customers, "accounts": g.accounts, "counterparties": g.counterparties,
        "transactions": g.txns, "digital_events": sorted(g.events, key=lambda e: e["EVENT_TS"]),
        "loans": g.loans, "liquidity_daily": liquidity, "country_risk": country_rows, "watchlist": watch_rows,
        "planted_cases": g.planted,
    }
    for name, rows in tables.items():
        write_csv(os.path.join(args.out, f"{name}.csv"), rows)
    manifest = {"seed": args.seed, "as_of": AS_OF.isoformat(), "window_start": START.isoformat(),
                "row_counts": {k: len(v) for k, v in tables.items()}}
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
