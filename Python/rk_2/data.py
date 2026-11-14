from __future__ import annotations
from pathlib import Path
import pandas as pd
YEARS = list(range(2014, 2027))
FIELDS = ['cve_id', 'date', 'attack_type', 'vendor', 'product', 'cvss_score', 'severity', 'attack_vector', 'access_complexity', 'privileges_required', 'user_interaction', 'confidentiality_impact', 'integrity_impact', 'availability_impact', 'attacker_country', 'target_sector', 'affected_hosts', 'status', 'exploit_available']
CATEGORICAL = ['attack_type', 'severity', 'attack_vector', 'attacker_country', 'target_sector']
DEFAULTS = {'years': YEARS.copy(), 'attack_type': [], 'severity': [], 'attack_vector': [], 'attacker_country': [], 'target_sector': [], 'cvss_min': 0.0, 'exploit_only': False, 'exploited_only': False}

def default_filters():
    return {'years': YEARS.copy(), **{col: [] for col in CATEGORICAL}, 'cvss_min': 0.0, 'exploit_only': False, 'exploited_only': False}

def normalize_filters(settings: dict | None) -> dict:
    src = settings if isinstance(settings, dict) else {}
    result = default_filters()
    try:
        years = src.get('years', YEARS)
        if not isinstance(years, (list, tuple)):
            years = YEARS
        result['years'] = sorted({int(y) for y in years if str(y).isdigit() and int(y) in YEARS})
    except (ValueError, TypeError):
        result['years'] = YEARS.copy()
    for col in CATEGORICAL:
        values = src.get(col, [])
        result[col] = list(dict.fromkeys((v for v in values if isinstance(v, str)))) if isinstance(values, list) else []
    try:
        minimum = float(src.get('cvss_min', 0.0))
        result['cvss_min'] = max(0.0, min(10.0, minimum)) if pd.notna(minimum) else 0.0
    except (ValueError, TypeError):
        pass
    for key in ('exploit_only', 'exploited_only'):
        result[key] = src.get(key) is True
    return result

def read_datasets(directory: str | Path, years: tuple[int, ...] | list[int]):
    directory = Path(directory)
    chunks = []
    warnings = []
    for year in sorted(set((int(y) for y in years))):
        if year not in YEARS:
            warnings.append(f'Недопустимый год: {year}')
            continue
        file = directory / f'cyberattacks_cve_{year}.csv'
        if not file.is_file():
            warnings.append(f'Не найден {file.name}')
            continue
        try:
            frame = pd.read_csv(file, encoding='utf-8-sig', on_bad_lines='error', low_memory=False, dtype={'cve_id': 'string'})
            missing = set(FIELDS) - set(frame.columns)
            if missing:
                raise ValueError('Отсутствуют поля: ' + ', '.join(sorted(missing)))
            frame = frame.copy()
            rows_before = len(frame)
            frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
            frame['cvss_score'] = pd.to_numeric(frame['cvss_score'], errors='coerce')
            frame['affected_hosts'] = pd.to_numeric(frame['affected_hosts'], errors='coerce')
            for col in CATEGORICAL + ['status', 'exploit_available', 'vendor', 'product', 'cve_id']:
                frame[col] = frame[col].fillna('Не указано').astype(str).str.strip()
            valid = frame['date'].notna() & frame['date'].dt.year.eq(year) & frame['cvss_score'].between(0, 10, inclusive='both') & frame['affected_hosts'].ge(0) & frame['affected_hosts'].mod(1).eq(0) & frame['cve_id'].str.fullmatch('CVE-\\d{4}-\\d{4,}', case=False, na=False) & frame['cve_id'].str.slice(4, 8).eq(str(year))
            frame = frame.loc[valid].copy()
            frame['cve_id'] = frame['cve_id'].str.upper()
            duplicate_count = int(frame['cve_id'].duplicated().sum())
            if duplicate_count:
                frame = frame.drop_duplicates('cve_id', keep='first')
            removed = rows_before - len(frame)
            if removed:
                warnings.append(f'{file.name}: пропущено {removed} некорректных или повторных записей')
            frame['affected_hosts'] = frame['affected_hosts'].astype('int64')
            frame['year'] = year
            chunks.append(frame)
        except (OSError, UnicodeError, ValueError, TypeError, pd.errors.ParserError) as exc:
            warnings.append(f'{file.name}: ошибка чтения — {exc}')
    if not chunks:
        return (pd.DataFrame(columns=FIELDS + ['year']), warnings)
    return (pd.concat(chunks, ignore_index=True), warnings)

def apply_filters(frame: pd.DataFrame, settings: dict):
    if frame.empty:
        return frame.copy()
    settings = normalize_filters(settings)
    if not settings['years']:
        return frame.iloc[0:0].copy()
    mask = frame['year'].isin(settings['years'])
    for field in CATEGORICAL:
        values = settings[field]
        if values:
            mask &= frame[field].isin(values)
    mask &= frame['cvss_score'].ge(settings['cvss_min'])
    if settings['exploit_only']:
        mask &= frame['exploit_available'].str.casefold().eq('yes')
    if settings['exploited_only']:
        mask &= frame['status'].str.casefold().eq('exploited')
    return frame.loc[mask].copy()

def get_metrics(frame: pd.DataFrame):
    return {'total': len(frame), 'avg_cvss': round(float(frame['cvss_score'].mean()), 2) if not frame.empty and frame['cvss_score'].notna().any() else 0.0, 'critical': int(frame['severity'].str.casefold().eq('critical').sum()) if not frame.empty else 0, 'affected': int(frame['affected_hosts'].sum()) if not frame.empty else 0}
