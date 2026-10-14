"""Norwegian organisation number helpers (9 digits, modulus-11 check digit)."""

import re

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def normalize(raw: str) -> str:
    """Keep digits only. Accepts '923 609 016', 'NO923609016MVA' and similar."""
    return re.sub(r"\D", "", str(raw or ""))


def is_valid(orgnr: str) -> bool:
    digits = normalize(orgnr)
    if len(digits) != 9:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:8], _WEIGHTS))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False
    return check == int(digits[8])
