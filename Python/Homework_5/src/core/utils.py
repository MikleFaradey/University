from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import uuid

def cents(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid monetary amount')
    if not number.is_finite() or number <= 0 or number.as_tuple().exponent < -2:
        raise ValueError('Amount must be positive with at most two decimal places')
    return int(number * 100)

def money(value):
    return str(Decimal(value) / Decimal(100))

def now(): return datetime.now(timezone.utc).isoformat()
def operation_id(): return uuid.uuid4().hex
