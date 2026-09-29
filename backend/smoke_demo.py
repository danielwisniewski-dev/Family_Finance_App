"""Repeatable demo parity smoke with disposable data and forbidden outbound calls.

Run: python -m backend.smoke_demo
Extend this flow when new financial actions or bank features are introduced.
"""
from __future__ import annotations

import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from backend.app.dates import household_today
from backend.app.db import BudgetRepository
from backend.app.hosted import Application


def run_smoke() -> dict:
    with tempfile.TemporaryDirectory(prefix="ledger-demo-parity-") as temporary:
        real = BudgetRepository(Path(temporary) / "synthetic-real.sqlite")
        real.initialize()
        household = real.create_household("Private sentinel", spouses=[
            {"name": "Sentinel", "username": "sentinel", "password": "synthetic-sentinel-only"}])
        real.create_budget_month(household_id=household, month=household_today().strftime("%Y-%m"))
        token = real.authenticate_local_user("sentinel", "synthetic-sentinel-only")["token"]
        app = Application(real)

        def request(method, path, payload=None, bearer=None, expected=200):
            data = json.dumps(payload or {}).encode()
            environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(data),
                       "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(data))}
            if bearer:
                environ["HTTP_AUTHORIZATION"] = "Bearer " + bearer
            status = []
            raw = b"".join(app(environ, lambda code, headers: status.append(int(code.split()[0]))))
            body = json.loads(raw)
            assert status == [expected], (method, path, status, body.get("message"))
            return body

        try:
            # Any accidental use of a real bank/coach transport fails this smoke.
            with patch("socket.socket.connect", side_effect=AssertionError("Demo attempted an outbound connection")), \
                    patch("urllib.request.urlopen", side_effect=AssertionError("Demo attempted an outbound HTTP call")):
                first = request("POST", "/demo/start", bearer=token)
                demo = first["token"]
                month = first["budget_month_id"]
                baseline = real.db_path.read_bytes()

                def demo_request(method, path, payload=None, expected=200):
                    result = request(method, "/demo" + path, payload, demo, expected)
                    assert result.get("demo") is True
                    assert "Private sentinel" not in json.dumps(result)
                    return result

                detail = demo_request("GET", f"/budget-months/{month}/budget-detail")
                categories = {c["name"]: c["id"] for g in detail["groups"] for c in g["categories"]}
                check = {"budget_month_id": month, "category_id": categories["Groceries"], "purchase_amount_cents": 2500}
                result = demo_request("POST", "/safe-to-spend", check)
                assert "After upcoming bills, you would have about $" in json.dumps(result)
                demo_request("POST", "/coach/safe-to-spend", check)
                original = demo_request("GET", f"/budget-months/{month}/funds")["funds"]
                fund = next(f for f in original if f["name"] == "Car Repairs")
                assert all(f["balance_cents"] > 0 for f in original)
                contribution = {"budget_month_id": month, "kind": "contribution", "amount_cents": 2500,
                                "occurred_on": household_today().isoformat(), "idempotency_key": "demo-smoke-contribution"}
                demo_request("POST", f"/funds/{fund['id']}/entries", contribution)
                demo_request("POST", f"/funds/{fund['id']}/entries", contribution)
                funded = demo_request("GET", f"/budget-months/{month}/funds")["funds"]
                assert next(f for f in funded if f["id"] == fund["id"])["balance_cents"] == fund["balance_cents"] + 2500
                gifts = next(f for f in original if f["name"] == "Gifts")
                demo_request("POST", f"/funds/{fund['id']}/entries", contribution | {
                    "kind": "release", "amount_cents": 500, "idempotency_key": "demo-smoke-release"})
                demo_request("POST", f"/funds/{fund['id']}/transfer", {
                    "budget_month_id": month, "target_fund_id": gifts["id"], "amount_cents": 1000,
                    "occurred_on": household_today().isoformat(), "idempotency_key": "demo-smoke-move"})
                balances = {f["id"]: f["balance_cents"] for f in demo_request("GET", f"/budget-months/{month}/funds")["funds"]}
                assert balances[fund["id"]] == fund["balance_cents"] + 1000
                assert balances[gifts["id"]] == gifts["balance_cents"] + 1000

                def category_totals():
                    return {c["id"]: c for c in demo_request("GET", f"/budget-months/{month}/summary")["categories"]}

                totals = category_totals()
                demo_request("POST", "/spending", {"category_id": categories["Groceries"], "amount_cents": 1000,
                    "occurred_on": household_today().isoformat(), "note": "Demo cash purchase"}, expected=201)
                assert category_totals()[categories["Groceries"]]["spent_cents"] == totals[categories["Groceries"]]["spent_cents"] + 1000
                demo_request("PATCH", f"/categories/{categories['Groceries']}", {
                    "name": "Demo groceries edited", "planned_cents": totals[categories["Groceries"]]["planned_cents"] + 1000})
                demo_request("PATCH", f"/categories/{categories['Fun Money']}", {
                    "planned_cents": totals[categories["Fun Money"]]["planned_cents"] - 1000})
                assert demo_request("GET", f"/budget-months/{month}/summary")["unassigned_cents"] == 0
                next_month = (household_today().replace(day=28) + timedelta(days=4)).replace(day=1)
                new_month = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
                created = demo_request("POST", "/budget-months", {"household_id": first["household"]["id"],
                    "month": new_month, "copy_from_budget_month_id": month}, expected=201)
                copied = demo_request("GET", f"/budget-months/{created['id']}/budget-detail")
                assert "Demo groceries edited" in json.dumps(copied)
                assert len(demo_request("GET", f"/budget-months/{created['id']}/funds")["funds"]) == len(original)

                # Advisory coach output may suggest a change but never applies it.
                before_advice = category_totals()
                advice = demo_request("POST", "/coach/budget-change-suggestion", {"budget_month_id": month,
                    "amount_cents": 500, "from_category_id": categories["Fun Money"],
                    "to_category_id": categories["Groceries"], "purpose": "A larger grocery trip"})
                assert advice["coach"]["proposed_budget_change"]["status"] == "draft_only"
                assert category_totals() == before_advice
                status = demo_request("GET", f"/budget-months/{month}/bank-status")
                item = status["connection_id"]
                for kind in ("balance", "transaction"):
                    outcome = demo_request("POST", "/plaid/sync", {"plaid_item_id": item, "sync_type": kind})
                    assert outcome["success"]
                transactions = demo_request("GET", f"/budget-months/{month}/transactions")["transactions"]
                outcome = demo_request("POST", "/plaid/sync", {"plaid_item_id": item, "sync_type": "transaction"})
                assert outcome["inserted_transactions"] == 0
                assert len(demo_request("GET", f"/budget-months/{month}/transactions")["transactions"]) == len(transactions)
                queue = demo_request("GET", f"/budget-months/{month}/transaction-review-queue")["transactions"]
                assert queue, "Sync must supply transactions to demonstrate ordinary review"
                demo_request("POST", "/safe-to-spend", check, expected=400)
                for txn in queue:
                    if txn["transaction"]["merchant_name"] == "Willow Home Goods":
                        demo_request("PATCH", f"/transactions/{txn['transaction']['id']}/split", {"splits": [
                            {"category_id": categories["Groceries"], "amount_cents": 1000},
                            {"category_id": categories["Household Supplies"], "amount_cents": 1399}], "reviewed": True})
                    else:
                        demo_request("PATCH", f"/transactions/{txn['transaction']['id']}/category",
                                     {"category_id": categories["Groceries"], "reviewed": True})
                demo_request("POST", "/merchant-category-rules", {"category_id": categories["Household Supplies"],
                    "merchant_match_text": "Willow Home Goods", "apply_to_existing_unreviewed": False}, expected=201)
                # Reapplying a recorded refund and ignoring an internal transfer
                # must preserve totals; the original seed covers their history.
                before_corrections = category_totals()
                refund = next(t["transaction"] for t in transactions if t["transaction"]["name"] == "Oak Street Auto Refund")
                demo_request("POST", f"/transactions/{refund['id']}/refund", {"category_id": fund["category_id"]})
                transfer = next(t["transaction"] for t in transactions if t["transaction"]["name"] == "Transfer to Bills Checking")
                demo_request("PATCH", f"/transactions/{transfer['id']}/ignore", {"ignored": True, "reason": "Internal transfer"})
                assert category_totals() == before_corrections
                status = demo_request("GET", f"/budget-months/{month}/bank-status")
                assert status["unreviewed_spending"] == 0
                demo_request("POST", f"/budget-months/{month}/bank-reconciliation", {"revision": status["revision"]})
                demo_request("POST", "/safe-to-spend", check)
                demo_request("POST", "/plaid/refresh", {"plaid_item_id": item})
                link = demo_request("POST", "/plaid/link-token", expected=201)
                assert link["link_token"] == "demo-bank-link"
                demo_request("POST", "/plaid/exchange-public-token", {"budget_month_id": month,
                    "public_token": "demo-bank-confirmed"}, expected=201)
                demo_request("GET", "/settings/account")
                demo_request("GET", "/app/diagnostics")
                notifications = demo_request("GET", f"/budget-months/{month}/notifications")["notifications"]
                assert notifications
                demo_request("PATCH", f"/notifications/{notifications[0]['id']}/read")
                rules = demo_request("GET", "/merchant-category-rules")["rules"]
                assert any(r["merchant_match_text"] == "willow home goods" for r in rules)
                demo_request("POST", "/exit")
                request("GET", "/demo/budget-months", bearer=demo, expected=401)
                assert real.db_path.read_bytes() == baseline, "Demo operations changed the real database"
                fresh = request("POST", "/demo/start", bearer=token)
                assert fresh["token"] != demo
                fresh_detail = request("GET", f"/demo/budget-months/{month}/budget-detail", bearer=fresh["token"])
                assert "Demo groceries edited" not in json.dumps(fresh_detail)
                fresh_funds = request("GET", f"/demo/budget-months/{month}/funds", bearer=fresh["token"])["funds"]
                assert next(f for f in fresh_funds if f["id"] == fund["id"])["balance_cents"] == fund["balance_cents"]
                request("POST", "/demo/exit", bearer=fresh["token"])
                request("GET", "/budget-months", bearer=token)
                return {"ok": True, "funded_funds": len(original), "reviewed_new_transactions": len(queue),
                        "real_database_unchanged": True, "outbound_calls": 0,
                        "fresh_reentry": True, "normal_spending_guards": True,
                        "fund_contribute_release_move": True, "budget_edit_copy_manual_spending": True,
                        "transaction_split_refund_ignore_rules": True, "coach_advisory_only": True,
                        "notifications": True}
        finally:
            app.demo_manager.close()


if __name__ == "__main__":
    print(json.dumps(run_smoke(), indent=2))
