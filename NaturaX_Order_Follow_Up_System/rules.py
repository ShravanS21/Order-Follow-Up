"""Business rules. Thresholds come from the settings table (editable in the UI),
so changing a rule never needs a code change. Each rule returns an exception
(reason, priority, recommended action, hours-to-resolve) or nothing.
A rule only fires when the fields it needs are present and valid; otherwise the
import step has already logged a 'needs data correction' issue for that order."""

from datetime import timedelta

RULES = {
    "UNCONFIRMED": "Unconfirmed order",
    "DISPATCH_DELAY": "Dispatch delay",
    "SHIPMENT_DELAY": "Shipment delay",
    "FAILED_DELIVERY": "Failed delivery",
    "HIGH_VALUE_OVERDUE": "High-value overdue",
}
CLOSED = ("Delivered", "Cancelled")


def _hit(rule, reason, priority, action, since, grace_hours):
    """deadline = the moment the order became an exception + grace hours, so old problems are already overdue."""
    return dict(rule=rule, reason=reason, priority=priority, action=action, since=since, grace_hours=grace_hours)


def evaluate(o, cfg, now):
    """o: order dict with datetime fields (or None). Returns a list of hits."""
    hits = []
    st, od, dd, ed, val = o["status"], o["order_date"], o["dispatch_date"], o["expected_delivery"], o["order_value"]

    # 1. Unconfirmed for more than N hours
    if st == "Unconfirmed" and od:
        age = (now - od).total_seconds() / 3600
        if age > cfg["unconfirmed_hours"]:
            hits.append(_hit("UNCONFIRMED",
                f"Unconfirmed for {age:.1f}h (limit {cfg['unconfirmed_hours']:g}h)",
                "High" if age >= 12 else "Medium" if age >= 4 else "Low",
                "Call the customer to confirm the order" + (" and verify address (COD)" if o["payment_type"] == "COD" else ""),
                od + timedelta(hours=cfg["unconfirmed_hours"]), 2))

    # 2. Confirmed but not dispatched within N hours (order date is the clock start;
    #    the dataset has no separate confirmation timestamp)
    if st == "Confirmed" and od and dd is None:
        age = (now - od).total_seconds() / 3600
        if age > cfg["dispatch_hours"]:
            hits.append(_hit("DISPATCH_DELAY",
                f"Confirmed but not dispatched {age:.1f}h after order (limit {cfg['dispatch_hours']:g}h)",
                "High" if age > 2 * cfg["dispatch_hours"] else "Medium",
                "Ask warehouse to pack and hand over to courier; record dispatch date",
                od + timedelta(hours=cfg["dispatch_hours"]), 4))

    # 3. Dispatched and expected delivery date has passed
    if st == "Dispatched" and ed and ed < now:
        late = (now - ed).total_seconds() / 86400
        hits.append(_hit("SHIPMENT_DELAY",
            f"Expected delivery {ed:%d %b %Y} has passed ({late:.1f} day(s) late)",
            "High" if late >= 3 else "Medium" if late >= 1 else "Low",
            "Check tracking with courier and give the customer a revised delivery date", ed, 24))

    # 4. Failed delivery attempt: always immediate
    if st == "Failed Delivery":
        hits.append(_hit("FAILED_DELIVERY", "Delivery attempt failed",
            "High", "Call customer to confirm address/availability and request courier re-attempt", now, 2))

    # 5. High-value order still undelivered past expected date
    if val and val > cfg["high_value"] and st not in CLOSED and ed and ed < now:
        late = (now - ed).total_seconds() / 86400
        hits.append(_hit("HIGH_VALUE_OVERDUE",
            f"₹{val:,.0f} order (above ₹{cfg['high_value']:,.0f}) undelivered {late:.1f} day(s) past expected date",
            "High", "Escalate to manager; contact courier and customer today", ed, 4))
    return hits
