from replacement.state import TemporaryState


def test_ids_deposit_annul_snapshot_and_reset():
    state = TemporaryState()
    account = state.create_account("A")
    assert account.account_id == "AC-0001"
    operation = state.deposit(account.account_id, 125)
    assert operation.operation_id == "OP-0001"
    assert state.get_account(account.account_id).balance_cents == 125
    assert state.annul(operation.operation_id) == (True, True)
    assert state.annul(operation.operation_id) == (True, False)
    assert state.get_account(account.account_id).balance_cents == 0
    snapshot = state.snapshot()
    snapshot["accounts"].clear()
    assert state.get_account(account.account_id) is not None
    state.reset()
    assert state.create_account("B").account_id == "AC-0001"


def test_operation_counter_resets():
    state = TemporaryState()
    account = state.create_account("A")
    assert state.deposit(account.account_id, 1).operation_id == "OP-0001"
    state.reset()
    account = state.create_account("B")
    assert state.deposit(account.account_id, 1).operation_id == "OP-0001"
