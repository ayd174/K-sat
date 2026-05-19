"""AYKA Tapis postal-code WHITELIST — SOURCE OF TRUTH.

Three downstream sites are generated from this module:
  1. Akilli WhatsApp Asistani prompt — Bölüm 9.0 text block (Turkish "Grup X")
  2. Code node `_postal_classifier` — JS WHITELIST + GROUP_MIN constants
  3. Generate Confirmation Message sub-prompt — "Service area whitelist" block

To add/remove a postal code: edit POSTAL_GROUPS below, run the build script,
deploy. All three sites stay atomically in sync.
"""
from __future__ import annotations
from typing import Iterable

# =====================================================================
# SOURCE OF TRUTH — Belçika postal codes by group + zone minimum
# =====================================================================
POSTAL_GROUPS: dict[str, dict] = {
    'A': {
        'min_eur': 100,
        'codes': [
            '1180', '1160', '1170', '1500', '1630', '1640', '2830', '3070',
            '1820', '1840', '1860', '1861', '1970', '1950', '1980', '1730',
            '1650', '1785', '9300',
        ],
    },
    'B': {
        'min_eur': 60,
        'codes': ['1150', '1200', '1600', '1700', '1702', '1731', '1780', '1050'],
    },
    'C': {
        'min_eur': 50,
        'codes': [
            '1000', '1020', '1030', '1040', '1060', '1070', '1080', '1081',
            '1082', '1083', '1090', '1120', '1140', '1190', '1800', '1830',
            '1831', '1850', '1853', '1930', '1931', '1932', '1933',
        ],
    },
    'D': {
        'min_eur': 150,
        'codes': ['1410'],
    },
}


def total_codes() -> int:
    return sum(len(d['codes']) for d in POSTAL_GROUPS.values())


def all_pairs() -> Iterable[tuple[str, str]]:
    """(code, group) pairs in source-of-truth order."""
    for grp, data in POSTAL_GROUPS.items():
        for code in data['codes']:
            yield code, grp


# ---------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------

def render_js_whitelist(indent: str = '  ') -> str:
    """JS dict literal: var WHITELIST = { '1180':'A', ... };"""
    lines = ['var WHITELIST = {']
    for grp, data in POSTAL_GROUPS.items():
        codes = data['codes']
        # 8 codes per visual line for readability
        for i in range(0, len(codes), 8):
            chunk = codes[i:i + 8]
            entries = ','.join(f"'{c}':'{grp}'" for c in chunk)
            lines.append(f"{indent}{entries},")
    # Strip trailing comma on the LAST entry line
    if lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]
    lines.append('};')
    return '\n'.join(lines)


def render_js_group_min() -> str:
    """JS dict literal: var GROUP_MIN = { A: 100, ... };"""
    entries = ', '.join(f"{g}: {d['min_eur']}" for g, d in POSTAL_GROUPS.items())
    return 'var GROUP_MIN = { ' + entries + ' };'


def render_prompt_block_b9() -> str:
    """Prompt Bölüm 9.0 four indented lines.
    Existing format (matched): 4-space indent, label padded to 13 chars + ': '.
    """
    out = []
    for grp, data in POSTAL_GROUPS.items():
        codes_str = ' '.join(data['codes'])
        label = f"Grup {grp} ({data['min_eur']}€)"
        lbl_padded = label.ljust(13)
        out.append(f"    {lbl_padded}: {codes_str}")
    return '\n'.join(out)


def render_confirmation_block(indent: str = '     ') -> str:
    """Generate Confirmation Message subprompt — English 'Group X: codes'."""
    out = []
    for grp, data in POSTAL_GROUPS.items():
        codes_str = ' '.join(data['codes'])
        out.append(f"{indent}Group {grp}: {codes_str}")
    return '\n'.join(out)


# =====================================================================
# FEATURED POSITIVE EXAMPLES — covering all 4 groups, frequently violated
# =====================================================================
# α-2 (BÖLÜM 0) and Bölüm 9.0 ÖZEL DİKKAT each list 5 featured codes.
# Two orderings/labels are kept to preserve current prompt structure.
# All codes MUST exist in POSTAL_GROUPS (validated below).

FEATURED_ALPHA2: list[tuple[str, str]] = [
    ('1410', 'Waterloo'),
    ('1190', 'Forest'),
    ('1090', 'Jette'),
    ('1500', 'Halle'),
    ('1731', 'Asse'),
]
FEATURED_B9: list[tuple[str, str]] = [
    ('1410', 'Waterloo'),
    ('1190', 'Forest'),
    ('1090', 'Jette'),
    ('1731', 'Asse/Zellik'),
    ('1500', 'Halle'),
]


def _group_min_for(code: str) -> tuple[str, int]:
    for grp, data in POSTAL_GROUPS.items():
        if code in data['codes']:
            return grp, data['min_eur']
    raise ValueError(f"Featured code {code!r} not in POSTAL_GROUPS")


def render_alpha2_positives() -> str:
    """α-2 POZİTİF ÖRNEKLER block.

    Format (matches v9.12.7 exactly):
      - 1410 (Waterloo) → Grup D → 150€ min → KAPSAMDA
      - 1190 (Forest)   → Grup C →  50€ min → KAPSAMDA
      ...
    """
    max_paren = max(len(f"({lbl})") for _, lbl in FEATURED_ALPHA2)
    out = []
    for code, lbl in FEATURED_ALPHA2:
        grp, min_eur = _group_min_for(code)
        paren = f"({lbl})".ljust(max_paren + 1)  # +1 trailing space before arrow
        min_str = f"{min_eur:>3}€"
        out.append(f"  - {code} {paren}→ Grup {grp} → {min_str} min → KAPSAMDA")
    return '\n'.join(out)


def render_b9_special_attention() -> str:
    """Bölüm 9.0 ÖZEL DİKKAT — SIK İHLAL EDİLEN block.

    Format (matches v9.12.7):
      1410 (Waterloo)    → Grup D → 150€ min → ✅ KAPSAMDA
      1190 (Forest)      → Grup C → 50€ min  → ✅ KAPSAMDA
      ...
    """
    max_paren = max(len(f"({lbl})") for _, lbl in FEATURED_B9)
    out = []
    for code, lbl in FEATURED_B9:
        grp, min_eur = _group_min_for(code)
        paren = f"({lbl})".ljust(max_paren + 1)
        min_part = f"{min_eur}€ min".ljust(9)
        out.append(f"  {code} {paren}→ Grup {grp} → {min_part}→ ✅ KAPSAMDA")
    return '\n'.join(out)


# Validate featured codes at import time
def _validate_featured():
    all_codes = {c for c, _ in all_pairs()}
    for code, _ in FEATURED_ALPHA2 + FEATURED_B9:
        if code not in all_codes:
            raise ValueError(f"FEATURED code {code!r} not in POSTAL_GROUPS — inconsistent SOURCE")

_validate_featured()


# =====================================================================
# Confusing Grup C codes — peripheral Brussels that LOOK like Grup A
# =====================================================================
# These codes are geographically near Brussels and customers/staff sometimes
# assume they should be Grup A (100€). Bölüm 9.0 has a clarification block
# stating they are actually Grup C (50€). Each entry MUST be in POSTAL_GROUPS['C'].

CONFUSING_GROUPC_CODES: list[tuple[str, str]] = [
    ('1831', 'Diegem'),
    ('1800', 'Vilvoorde'),
    ('1850', 'Grimbergen'),
    ('1930', 'Zaventem'),
    ('1830', 'Machelen'),
]


def _validate_confusion():
    for code, label in CONFUSING_GROUPC_CODES:
        grp = next((g for g, d in POSTAL_GROUPS.items() if code in d['codes']), None)
        if grp != 'C':
            raise ValueError(
                f"CONFUSING_GROUPC_CODES: {code} ({label}) is Grup {grp or 'NONE'} in POSTAL_GROUPS, "
                f"but listed as confusing-Grup-C — fix POSTAL_GROUPS or remove from confusion list"
            )

_validate_confusion()


def render_confusion_groupc_block() -> str:
    """Bölüm 9.0 confusion block for peripheral-Brussels Grup C codes.

    Format (matches v9.12.7 exactly):
      ⚠️ ÖZEL DİKKAT — Diegem (1831), Vilvoorde (1800), Grimbergen (1850),
        Zaventem (1930), Machelen (1830):
        Bu kodlar GRUP C'dir (50€), Grup A DEĞİL.
        Müşteri "vous venez à partir de 50€ chez moi" derse, bu kodlar
        için DOĞRUDUR.

    Line break is hardcoded after the 3rd item (Grimbergen) to preserve
    original visual structure. If list grows past 6 items this rendering
    will need adjustment.
    """
    grp_c_min = POSTAL_GROUPS['C']['min_eur']
    parts = [f"{label} ({code})" for code, label in CONFUSING_GROUPC_CODES]
    # Split: first 3 items on line 1, rest on line 2
    line1 = ', '.join(parts[:3])
    line2 = ', '.join(parts[3:])
    return (
        f"  ⚠️ ÖZEL DİKKAT — {line1},\n"
        f"    {line2}:\n"
        f"    Bu kodlar GRUP C'dir ({grp_c_min}€), Grup A DEĞİL.\n"
        f"    Müşteri \"vous venez à partir de {grp_c_min}€ chez moi\" derse, bu kodlar\n"
        f"    için DOĞRUDUR."
    )


# =====================================================================
# Group min legend + drift verifier
# =====================================================================

def render_group_min_legend() -> str:
    """One-line legend used in α-2 step 2: 'A=100€, B=60€, C=50€, D=150€'."""
    return ', '.join(f"{g}={d['min_eur']}€" for g, d in POSTAL_GROUPS.items())


def verify_postal_group_drift(text: str) -> list[str]:
    """Scan free-form prompt text for `1180 (Grup A min 100€)` / `(Grup A, min 100€)`
    patterns and report mismatches against POSTAL_GROUPS.

    Catches calculation-example drift without forcing rewrites.
    Returns a list of human-readable issue strings (empty = clean).
    """
    import re
    issues: list[str] = []

    # Form 1: '1180 (Grup A min 100€)' / '1180 (Grup A, min 100€)'
    pat1 = re.compile(r'(\d{4})\s+\(Grup ([A-D]),?\s+min\s+(\d+)€\)')
    for m in pat1.finditer(text):
        code, claimed_grp, claimed_min = m.group(1), m.group(2), int(m.group(3))
        actual_grp = next((g for g, d in POSTAL_GROUPS.items() if code in d['codes']), None)
        if actual_grp is None:
            issues.append(f"  drift: postal {code} mentioned as Grup {claimed_grp} but not in any source group")
        elif actual_grp != claimed_grp:
            issues.append(f"  drift: postal {code} claimed Grup {claimed_grp} but source says Grup {actual_grp}")
        elif claimed_min != POSTAL_GROUPS[actual_grp]['min_eur']:
            issues.append(
                f"  drift: postal {code} min={claimed_min}€ in text but Grup {actual_grp} source min={POSTAL_GROUPS[actual_grp]['min_eur']}€"
            )

    # Form 2: bare '(Grup A min 100€)' / '(Grup A, min 100€)' without explicit postal
    pat2 = re.compile(r'\(Grup ([A-D]),?\s+min\s+(\d+)€\)')
    for m in pat2.finditer(text):
        # Skip if this match overlaps a Form-1 match (already counted)
        start = m.start()
        if pat1.search(text[max(0, start - 6):start + len(m.group(0))]):
            continue
        claimed_grp = m.group(1)
        claimed_min = int(m.group(2))
        expected = POSTAL_GROUPS[claimed_grp]['min_eur']
        if claimed_min != expected:
            issues.append(f"  drift: bare '(Grup {claimed_grp} min {claimed_min}€)' but source min={expected}€")

    return issues


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
    print(f"=== POSTAL_GROUPS summary ===")
    print(f"  Total codes: {total_codes()}")
    for grp, data in POSTAL_GROUPS.items():
        print(f"  Group {grp} ({data['min_eur']}€): {len(data['codes'])} codes")
    print()
    print("=== JS WHITELIST ===")
    print(render_js_whitelist())
    print()
    print("=== JS GROUP_MIN ===")
    print(render_js_group_min())
    print()
    print("=== Prompt Bölüm 9.0 block ===")
    print(render_prompt_block_b9())
    print()
    print("=== Confirmation subprompt block ===")
    print(render_confirmation_block())
    print()
    print("=== α-2 POZİTİF ÖRNEKLER ===")
    print(render_alpha2_positives())
    print()
    print("=== Bölüm 9.0 ÖZEL DİKKAT ===")
    print(render_b9_special_attention())
    print()
    print("=== Group min legend ===")
    print(render_group_min_legend())
    print()
    print("=== Confusion Grup C block ===")
    print(render_confusion_groupc_block())
