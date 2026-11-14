from __future__ import annotations
import hashlib
from pathlib import Path
REFERENCE_COUNTS = {2014: 1028, 2015: 950, 2016: 974, 2017: 1149, 2018: 1725, 2019: 1036, 2020: 1018, 2021: 818, 2022: 998, 2023: 1549, 2024: 1681, 2025: 1015, 2026: 1906}
REFERENCE_GIT_SHA = {2014: 'b372d7e938410d1377e5e643d15214d169e18410', 2015: '2b29399d76eb972bfcfd2e8375155d55c0f02d4a', 2016: 'c208965af13bfefcd5381888e3e86faf596f8c6b', 2017: '278319292639cf8a16804eda949ca2c7e0b9fd69', 2018: '285b57e16583905589e4ff31c236dc6a36de4087', 2019: '0fc0217e1883d987bbad7b762b73dc28792bd82b', 2020: '9f7febfb31a873bef9f62eb8cbe2e348d2489c33', 2021: '23b54041b98896f000f20e33040f954d45b6f8b7', 2022: 'a70fbcc8fa8f849d39bf3652afa0e3fb7a90057b', 2023: '25810478b5dfd27ac28e7c31e761baf303b1ac06', 2024: 'eacbe5df73bda53346000eb2508b0bd830046c00', 2025: 'de55f8ff05308d8f0c0ea60a54a70a3db4d65e33', 2026: '19c1400c2bfb288a119f73265d38f648884429bd'}

def git_blob_sha(path: str | Path) -> str:
    data = Path(path).read_bytes()
    prefix = f'blob {len(data)}\x00'.encode('ascii')
    return hashlib.sha1(prefix + data).hexdigest()

def matches_reference(path: str | Path, year: int) -> bool:
    return git_blob_sha(path) == REFERENCE_GIT_SHA[year]
