#!/usr/bin/env python3
"""
Automated wrapper for tune_clustering.py.
Feeds pre-determined article selections and same-event groupings as stdin.

Article groupings based on analysis of 144 articles from 2026-08-14.

Run:
    python /home/krish/.gemini/antigravity-ide/brain/4bc95e9d-faad-4cba-87b2-593f4a8e29c4/scratch/run_tune_auto.py
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Selected article indices from the full 144-article list for 2026-08-14.
# These 32 articles were chosen because they contain clear same-event pairs.
# ---------------------------------------------------------------------------
SELECTED_ORIG_INDICES = [
    1, 4, 6, 7, 8, 9, 10, 11, 15, 16, 19, 24, 25, 32, 33,
    37, 38, 39, 42, 60, 71, 72, 73, 80, 81, 97, 117, 118, 120, 129, 138, 140,
]

# ---------------------------------------------------------------------------
# Mapping of selected indices (0-based) to original indices for reference:
#
# selected[ 0] = orig[  1] = Gorakhpur-Delhi Amrit Bharat Express: route/timings (IE)
# selected[ 1] = orig[  4] = Drug cartel boss extradited from UAE, Amit Shah (IE)
# selected[ 2] = orig[  6] = 40 questions cleared for Census 2027 incl. caste/Aadhaar (IE)
# selected[ 3] = orig[  7] = Triple hydraulic failure in Phuket-Delhi flight (IE)
# selected[ 4] = orig[  8] = Sukhbir Singh Badal after discharge: 'I am not scared' (TOI)
# selected[ 5] = orig[  9] = SC quashes FIRs vs Samay Raina, Ranveer Allahabadia IGL (TOI)
# selected[ 6] = orig[ 10] = BCI action, U-turn and SC rebuke: NALSAR protest vs CJI (TOI)
# selected[ 7] = orig[ 11] = Iran president Pezeshkian to visit India for BRICS (TOI)
# selected[ 8] = orig[ 15] = India's first Vande Bharat freight train 130 kmph trial (IE)
# selected[ 9] = orig[ 16] = Former women Naxalites share Raipur ramp-walk experience (TOI)
# selected[10] = orig[ 19] = GOBARdhan scheme: cattle dung/crop waste into fuel (TOI)
# selected[11] = orig[ 24] = Iran President to visit India for BRICS Summit (IE)
# selected[12] = orig[ 25] = Govt comprehensive steps to reform public exams: Pres Murmu (IE)
# selected[13] = orig[ 32] = Har Ghar Tiranga rally with 1,000-foot flag in A.P. Kadiri (Hindu)
# selected[14] = orig[ 33] = ₹22,500 crore MoU Bihar company has only ₹11 lakh capital (Hindu)
# selected[15] = orig[ 37] = Attack on Badal: Accused sent to police custody till Aug 24 (Hindu)
# selected[16] = orig[ 38] = Terrorists will face consequences: Pres Murmu addresses nation (TOI)
# selected[17] = orig[ 39] = Amrit Bharat Express trains to halt at Mancherial/Peddapalli (Hindu)
# selected[18] = orig[ 42] = Full version of Vande Mataram: rules for rendition (Hindu)
# selected[19] = orig[ 60] = Vande Mataram's Independence Day debut and its significance (Hindu)
# selected[20] = orig[ 71] = President Murmu approves 78 gallantry awards, 13 posthumous (TOI)
# selected[21] = orig[ 72] = Partition Horrors Remembrance Day at Mysuru railway station (Hindu)
# selected[22] = orig[ 73] = Govt taking comprehensive reforms to curb exam paper leaks: President (Hindu)
# selected[23] = orig[ 80] = Three sisters killed by uncle in West Bengal's Murshidabad (Hindu)
# selected[24] = orig[ 81] = 'Architects of India's future': Pres Murmu's praise for students (IE)
# selected[25] = orig[ 97] = Documentary on partition horrors screened at Tirupati (Hindu)
# selected[26] = orig[117] = Census 2027: Centre notifies 40 questions for second phase (Hindu)
# selected[27] = orig[118] = NALSAR alumni condemn BCI letters (Hindu)
# selected[28] = orig[120] = 7 dead, 3 missing: water/debris enters Uttarakhand hydro tunnel (Hindu)
# selected[29] = orig[129] = RGUKT Students organise Har Ghar Tiranga rally (Hindu)
# selected[30] = orig[138] = Pres Droupadi Murmu's address to nation on eve of 80th I-Day (Hindu)
# selected[31] = orig[140] = 1,057 police personnel awarded Gallantry, service medals (Hindu)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Same-event groups (indices into the *selected* list, 0-based):
#
# Group 1: [7, 11]
#   Iran President Pezeshkian to visit India for BRICS Summit
#   - TOI: "Iran president Pezeshkian to visit India for BRICS summit"
#   - IE:  "Iran President to visit India for BRICS Summit"
#
# Group 2: [4, 15]
#   Sukhbir Singh Badal attack aftermath
#   - TOI: "'I am not scared': Sukhbir Singh Badal after discharge day after attack"
#   - Hindu: "Attack on Badal: Accused sent to police custody till August 24"
#
# Group 3: [12, 16, 22, 24, 30]
#   President Murmu's Independence Day eve address to the nation
#   - IE (25): "Govt taking comprehensive steps to reform public exams, says Pres Murmu in I-day speech"
#   - TOI (38): "'Terrorists will face consequences': Pres Murmu addresses nation on eve of 80th I-Day - key quotes"
#   - Hindu (73): "Govt taking comprehensive reforms to curb exam paper leaks: President on eve of 80th I-Day"
#   - IE (81): "'Architects of India's future': Pres Murmu's praise for students amid protests"
#   - Hindu (138): "President Droupadi Murmu's address to the nation on the eve of the 80th Independence Day"
#
# Group 4: [20, 31]
#   Independence Day gallantry / police medals
#   - TOI: "President Droupadi Murmu approves 78 gallantry awards, including 13 posthumous"
#   - Hindu: "1,057 police personnel awarded Gallantry, service medals; max from Chhattisgarh"
#
# Group 5: [2, 26]
#   Census 2027: 40 questions notified (including caste, Aadhaar)
#   - IE (6):   "40 questions cleared for Census 2027, including caste and Aadhaar details"
#   - Hindu (117): "Census 2027: Centre notifies 40 questions for second phase"
#
# Group 6: [6, 27]
#   NALSAR students / BCI protest row
#   - TOI (10): "BCI action, U-turn and SC rebuke: How NALSAR students' protest against CJI kicked up a row"
#   - Hindu (118): "NALSAR alumni condemn BCI letters"
#
# Group 7: [18, 19]
#   Vande Mataram: history and significance on Independence Day
#   - Hindu (42): "Full version of Vande Mataram: What are the rules for rendition of National Song"
#   - Hindu (60): "Vande Mataram's Independence Day debut and its significance"
#
# Group 8: [0, 17]
#   Amrit Bharat Express new trains
#   - IE (1):   "Gorakhpur-Delhi Amrit Bharat Express: Check train number, route, stops and timings"
#   - Hindu (39): "Newly sanctioned Amrit Bharat Express trains to halt at Mancherial and Peddapalli"
#
# Group 9: [13, 29]
#   Har Ghar Tiranga rallies on Independence Day eve
#   - Hindu (32): "'Har Ghar Tiranga' rally with 1,000-foot-long national flag in A.P.'s Kadiri town"
#   - Hindu (129): "RGUKT Students organise 'Har Ghar Tiranga' rally"
#
# Group 10: [21, 25]
#   Partition Horrors Remembrance Day
#   - Hindu (72): "Partition Horrors Remembrance Day observed at Mysuru railway station"
#   - Hindu (97): "Documentary on partition horrors screened at Regional Science Centre Tirupati"
# ---------------------------------------------------------------------------

GROUPS = [
    [7, 11],               # Group 1: Iran President BRICS visit
    [4, 15],               # Group 2: Sukhbir Singh Badal attack
    [12, 16, 22, 24, 30],  # Group 3: President Murmu I-Day address
    [20, 31],              # Group 4: Independence Day gallantry medals
    [2, 26],               # Group 5: Census 2027 40 questions
    [6, 27],               # Group 6: NALSAR/BCI protest
    [18, 19],              # Group 7: Vande Mataram significance
    [0, 17],               # Group 8: Amrit Bharat Express
    [13, 29],              # Group 9: Har Ghar Tiranga rally
    [21, 25],              # Group 10: Partition Horrors Remembrance
]


def build_stdin() -> str:
    lines = []
    # Step 1: article selection from full list
    lines.append(" ".join(str(i) for i in SELECTED_ORIG_INDICES))
    # Step 2: groupings
    for group in GROUPS:
        lines.append(" ".join(str(i) for i in group))
    lines.append("")  # blank line = done
    return "\n".join(lines) + "\n"


def main():
    script = Path("/home/krish/Dev/neutral-news/scripts/tune_clustering.py")
    stdin_data = build_stdin()

    print("=" * 70)
    print("  AUTO-TUNER: Piping pre-analyzed groupings to tune_clustering.py")
    print("=" * 70)
    print(f"\n  Date: 2026-08-14 (busiest day, 144 articles)")
    print(f"  Selected: {len(SELECTED_ORIG_INDICES)} articles")
    print(f"  Groups: {len(GROUPS)} same-event groups\n")
    for i, g in enumerate(GROUPS, 1):
        group_descriptions = {
            1: "Iran President BRICS visit",
            2: "Sukhbir Singh Badal attack aftermath",
            3: "President Murmu I-Day eve address (5 articles)",
            4: "Independence Day gallantry/police medals",
            5: "Census 2027: 40 questions notified",
            6: "NALSAR/BCI student protest row",
            7: "Vande Mataram Independence Day significance",
            8: "Amrit Bharat Express new trains",
            9: "Har Ghar Tiranga rallies",
            10: "Partition Horrors Remembrance Day",
        }
        print(f"    Group {i} (sel indices {g}): {group_descriptions.get(i, '')}")
    print()
    print("  Stdin being piped:")
    for line in stdin_data.splitlines():
        print(f"    >> {line!r}")
    print("\n" + "=" * 70 + "\n")

    result = subprocess.run(
        [sys.executable, str(script), "--date", "2026-08-14"],
        input=stdin_data,
        text=True,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
