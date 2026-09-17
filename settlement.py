from typing import List, Dict, Any

def compute_settlements(
    members: List[Dict[str, Any]], 
    expenses_with_splits: List[Dict[str, Any]], 
    refunds_with_splits: List[Dict[str, Any]]
) -> Dict[str, Any]:
    net_balances = {m["id"]: 0.0 for m in members}
    member_map = {m["id"]: m for m in members}

    # 1. Process Expenses
    for item in expenses_with_splits:
        payer_id = item.get("paid_by_member_id")
        splits = item.get("splits", [])
        for split in splits:
            debtor_id = split["member_id"]
            owed = float(split["owed_amount"])
            if payer_id in net_balances:
                net_balances[payer_id] += owed
            if debtor_id in net_balances:
                net_balances[debtor_id] -= owed

    # 2. Process Refunds
    for refund in refunds_with_splits:
        recipient_id = refund.get("recipient_member_id")
        splits = refund.get("splits", [])
        for split in splits:
            beneficiary_id = split["member_id"]
            credited_amt = float(split["credited_amount"])
            if recipient_id in net_balances:
                net_balances[recipient_id] -= credited_amt
            if beneficiary_id in net_balances:
                net_balances[beneficiary_id] += credited_amt

    # 3. Categorize into Debtors and Creditors
    debtors = []
    creditors = []
    for m_id, bal in net_balances.items():
        if bal < -0.01:
            debtors.append({"id": m_id, "amount": -bal})
        elif bal > 0.01:
            creditors.append({"id": m_id, "amount": bal})

    debtors.sort(key=lambda x: x["amount"], reverse=True)
    creditors.sort(key=lambda x: x["amount"], reverse=True)

    # 4. Greedy Debt Minimization
    transactions = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i]["amount"], creditors[j]["amount"])
        debtor_info = member_map.get(debtors[i]["id"], {"name": "Unknown", "upi_id": ""})
        creditor_info = member_map.get(creditors[j]["id"], {"name": "Unknown", "upi_id": ""})

        upi_intent = (
            f"upi://pay?pa={creditor_info.get('upi_id') or ''}"
            f"&pn={creditor_info.get('name') or ''}"
            f"&am={amount:.2f}&cu=INR&tn=WanderSplit-Settlement"
        )

        transactions.append({
            "from_id": debtors[i]["id"],
            "from_name": debtor_info.get("name"),
            "to_id": creditors[j]["id"],
            "to_name": creditor_info.get("name"),
            "amount": round(amount, 2),
            "payee_upi": creditor_info.get("upi_id"),
            "upi_intent": upi_intent
        })

        debtors[i]["amount"] -= amount
        creditors[j]["amount"] -= amount

        if debtors[i]["amount"] < 0.01:
            i += 1
        if creditors[j]["amount"] < 0.01:
            j += 1

    return {
        "net_balances": [
            {"member_id": m_id, "name": member_map[m_id]["name"], "net_amount": round(bal, 2)}
            for m_id, bal in net_balances.items()
        ],
        "minimized_transactions": transactions
    }