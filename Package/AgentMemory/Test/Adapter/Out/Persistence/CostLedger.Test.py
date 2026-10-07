import pytest
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time
from Package.AgentMemory.Src.Adapter.Out.Persistence.CostLedger import CostLedger, BudgetExceeded

def test_preflight_limit_and_unknown_charge(tmp_path):
    ledger = CostLedger(tmp_path/"budget.json")
    ticket = ledger.reserve("generation", 1_000_000, 1_000_000)
    assert ledger.summary()["accounted_cny"] == 16
    with pytest.raises(BudgetExceeded):
        ledger.reserve("generation", 1_000_000, 1_000_000)
    ledger.settle(ticket, {"prompt_tokens": 100, "completion_tokens": 50})
    assert ledger.summary()["estimated_cny"] == pytest.approx(.000215)
    CostLedger(tmp_path/"budget.json").reserve("embedding", 100)
    assert ledger.summary()["uncertain_calls"] == 1

def test_concurrent_reservations_cannot_overspend(tmp_path):
    path = tmp_path/"shared.json"
    def reserve(_):
        try:
            return CostLedger(path).reserve("embedding", 5_000_000)
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=4) as workers:
        tickets = list(workers.map(reserve, range(6)))
    assert sum(bool(t) for t in tickets) == 2
    assert CostLedger(path).summary()["accounted_cny"] == 20

def test_windows_cross_process_locked_file_can_be_opened(tmp_path):
    ledger = CostLedger(tmp_path/"cross_process.json")
    code = "from Package.AgentMemory.Src.Adapter.Out.Persistence.CostLedger import CostLedger; import sys; print(CostLedger(sys.argv[1]).summary()['calls'])"
    with ledger._state():
        child = subprocess.Popen([sys.executable,"-c",code,str(ledger.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        time.sleep(.3)
    stdout, stderr = child.communicate(timeout=15)
    assert child.returncode == 0, stderr
    assert stdout.strip() == "0"

def test_invalid_budget_or_bounds_cannot_disable_preflight(tmp_path):
    with pytest.raises(ValueError):
        CostLedger(tmp_path/"invalid.json",float("nan"))
    ledger=CostLedger(tmp_path/"valid.json")
    with pytest.raises(ValueError):
        ledger.reserve("embedding",-100)
    with pytest.raises(ValueError):
        ledger.reserve("unknown",100)
    assert ledger.summary()["calls"]==0

def test_invalid_usage_retains_reservation_and_settlement_is_idempotent(tmp_path):
    ledger = CostLedger(tmp_path/"usage.json")
    ticket = ledger.reserve("generation", 1000, 500)
    before = ledger.summary()["accounted_cny"]
    ledger.settle(ticket, {"prompt_tokens":True,"completion_tokens":False})
    assert ledger.summary()["accounted_cny"] == before
    assert ledger.summary()["uncertain_calls"] == 1
    ledger.settle(ticket, {"prompt_tokens":100,"completion_tokens":50})
    settled = ledger.summary()
    ledger.settle(ticket, {"prompt_tokens":1,"completion_tokens":0})
    assert ledger.summary() == settled
