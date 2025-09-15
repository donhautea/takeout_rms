from datetime import datetime
VAT_RATE_DEFAULT = 0.12
def ymd(date_like):
    if isinstance(date_like, str):
        for sep in ('-','/','.'):
            if sep in date_like:
                parts = date_like.split(sep)
                if len(parts)==3:
                    y,m,d = parts
                    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        return date_like
    return date_like.strftime('%Y-%m-%d')
def compute_profit_metrics(item_cost, tax_amount, other_costs, selling_price):
    total_cost = float(item_cost or 0)+float(tax_amount or 0)+float(other_costs or 0)
    est_profit = float(selling_price or 0)-total_cost
    margin = est_profit/float(selling_price) if selling_price else 0.0
    return {'total_cost': round(total_cost,2), 'est_profit': round(est_profit,2), 'profit_margin': round(margin,4)}
def compute_vat(vat_inclusive: bool, amount: float, vat_rate: float = VAT_RATE_DEFAULT):
    amount = float(amount or 0)
    if vat_inclusive:
        base = amount/(1+vat_rate); vat = amount-base; return round(vat,2), round(base,2)
    else:
        vat = amount*vat_rate; base = amount; return round(vat,2), round(base,2)
def peso(x):
    try: return f"₱{float(x):,.2f}"
    except Exception: return '₱0.00'
