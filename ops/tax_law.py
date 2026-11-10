"""The figures German income tax law sets per year, for the tax desk's workbook (TAX-05). One table, each figure with
its paragraph and where it was checked; docs/TAX-DESK.md cites the same sources. A year that is not in the table is
said so in the workbook: the desk never guesses a figure.

Checked on 10 Nov 2026 against the EStG on gesetze-im-internet.de (§ 4 Abs. 5 Nr. 6c, § 33 Abs. 3), the tables of
steuertipps.de for 2025 and 2026, and the Steueränderungsgesetz 2025 (Bundestag 4 Dec 2025, Bundesrat 19 Dec 2025),
which made the Entfernungspauschale 0.38 EUR from the first kilometre from 2026.

Read by ops/tax_book.py; imports nothing of the stack.
"""

SOURCES = {
    "estg": "https://www.gesetze-im-internet.de/estg/",
    "s4": "https://www.gesetze-im-internet.de/estg/__4.html",
    "s33": "https://www.gesetze-im-internet.de/estg/__33.html",
    "table": "https://www.steuertipps.de/finanzamt-formalitaeten/pauschbetraege-freibetraege-und-hoechstbetraege-fuer-die-steuererklaerung",
    "staendg2025": "https://www.bundestag.de/dokumente/textarchiv/2025/kw49-de-steueraenderungsgesetz-1128142",
    "bfh2017": "BFH, Urteil vom 19.01.2017, VI R 75/14 (zumutbare Belastung stufenweise)",
}

# Every figure in EUR. km_rates: (from km, rate per km) steps of the Entfernungspauschale per working day.
FIGURES = {
    2023: {"arbeitnehmer_pauschbetrag": 1230, "homeoffice_day": 6, "homeoffice_max": 1260, "km_rates": [(1, 0.30), (21, 0.38)],
           "km_cap": 4500, "sonderausgaben_pauschbetrag": (36, 72), "sparer_pauschbetrag": (1000, 2000),
           "altersvorsorge_max": (26528, 53056), "sonstige_vorsorge_max": (1900, 2800), "s35a_dienst": (0.20, 4000),
           "s35a_handwerk": (0.20, 1200), "grundfreibetrag": (10908, 21816), "gwg": 800},
    2024: {"arbeitnehmer_pauschbetrag": 1230, "homeoffice_day": 6, "homeoffice_max": 1260, "km_rates": [(1, 0.30), (21, 0.38)],
           "km_cap": 4500, "sonderausgaben_pauschbetrag": (36, 72), "sparer_pauschbetrag": (1000, 2000),
           "altersvorsorge_max": (27566, 55132), "sonstige_vorsorge_max": (1900, 2800), "s35a_dienst": (0.20, 4000),
           "s35a_handwerk": (0.20, 1200), "grundfreibetrag": (11784, 23568), "gwg": 800},
    2025: {"arbeitnehmer_pauschbetrag": 1230, "homeoffice_day": 6, "homeoffice_max": 1260, "km_rates": [(1, 0.30), (21, 0.38)],
           "km_cap": 4500, "sonderausgaben_pauschbetrag": (36, 72), "sparer_pauschbetrag": (1000, 2000),
           "altersvorsorge_max": (29344, 58688), "sonstige_vorsorge_max": (1900, 2800), "s35a_dienst": (0.20, 4000),
           "s35a_handwerk": (0.20, 1200), "grundfreibetrag": (12096, 24192), "gwg": 800},
    2026: {"arbeitnehmer_pauschbetrag": 1230, "homeoffice_day": 6, "homeoffice_max": 1260, "km_rates": [(1, 0.38)],
           "km_cap": 4500, "sonderausgaben_pauschbetrag": (36, 72), "sparer_pauschbetrag": (1000, 2000),
           "altersvorsorge_max": (30826, 61652), "sonstige_vorsorge_max": (1900, 2800), "s35a_dienst": (0.20, 4000),
           "s35a_handwerk": (0.20, 1200), "grundfreibetrag": (12348, 24696), "gwg": 800},
}

# § 33 Abs. 3 EStG: percent of the Gesamtbetrag der Einkünfte, by band (up to 15,340; to 51,130; above), per family case.
ZUMUTBAR_BANDS = (15340, 51130)
ZUMUTBAR = {"single": (5, 6, 7), "joint": (4, 5, 6), "kids_1_2": (2, 3, 4), "kids_3": (1, 1, 2)}

WHERE = {  # which source holds each figure
    "arbeitnehmer_pauschbetrag": "§ 9a Satz 1 Nr. 1a EStG (table)", "homeoffice_day": "§ 4 Abs. 5 Satz 1 Nr. 6c EStG (s4)",
    "homeoffice_max": "§ 4 Abs. 5 Satz 1 Nr. 6c EStG (s4)", "km_rates": "§ 9 Abs. 1 Satz 3 Nr. 4 EStG (table, staendg2025)",
    "km_cap": "§ 9 Abs. 1 Satz 3 Nr. 4 EStG (table)", "sonderausgaben_pauschbetrag": "§ 10c EStG (table)",
    "sparer_pauschbetrag": "§ 20 Abs. 9 EStG (table)", "altersvorsorge_max": "§ 10 Abs. 3 EStG (table)",
    "sonstige_vorsorge_max": "§ 10 Abs. 4 EStG (table)", "s35a_dienst": "§ 35a Abs. 2 EStG (table)",
    "s35a_handwerk": "§ 35a Abs. 3 EStG (table)", "grundfreibetrag": "§ 32a Abs. 1 EStG (table)", "gwg": "§ 6 Abs. 2 EStG (table)",
    "zumutbare_belastung": "§ 33 Abs. 3 EStG (s33), computed in steps (bfh2017)",
}


def figures(year):
    """-> the year's figures, or None when the table has no such year (the workbook then says so)."""
    return FIGURES.get(int(year))


def commute(year, km, days):
    """The Entfernungspauschale for the year: km one way times working days, by the year's steps; capped at km_cap,
    which does not hold for a commute by one's own car (the workbook says so). -> (amount, capped amount)."""
    f = figures(year)
    if not f or km is None or days is None:
        return None, None
    per_day, steps = 0.0, f["km_rates"] + [(10 ** 9, 0)]
    for (start, rate), (nxt, _) in zip(steps, steps[1:]):
        if km >= start:
            per_day += (min(km, nxt - 1) - start + 1) * rate
    total = round(per_day * days, 2)
    return total, min(total, f["km_cap"])


def homeoffice(year, days):
    f = figures(year)
    if not f or days is None:
        return None
    return min(days * f["homeoffice_day"], f["homeoffice_max"])


def zumutbar(income, case):
    """§ 33 Abs. 3 EStG in steps (BFH VI R 75/14): each band's share of the Gesamtbetrag at its own percentage."""
    if income is None or case not in ZUMUTBAR:
        return None
    lo, hi = ZUMUTBAR_BANDS
    pct = ZUMUTBAR[case]
    parts = [(min(income, lo), pct[0]), (max(0, min(income, hi) - lo), pct[1]), (max(0, income - hi), pct[2])]
    return round(sum(a * p / 100 for a, p in parts), 2)


def s35a(year, kind, labour):
    """20 % of the labour costs, capped per kind (handwerker or dienstleistung) -> the tax reduction."""
    f = figures(year)
    if not f or labour is None:
        return None
    share, cap = f["s35a_handwerk" if kind == "handwerker" else "s35a_dienst"]
    return min(round(labour * share, 2), cap)
