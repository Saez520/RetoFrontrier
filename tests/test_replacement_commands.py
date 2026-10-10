import pytest

from replacement.commands import dispatch
from replacement.state import TemporaryState


@pytest.mark.parametrize(("cents", "expected"), [(0, "0.00"), (1, "0.01"), (-1, "-0.01"), (500000, "5000.00")])
def test_consulta_formats_cents_exactly(cents, expected):
    state = TemporaryState()
    account = state.create_account("A")
    state._accounts[account.account_id].balance_cents = cents
    result = dispatch(f"CONSULTA;{account.account_id};00", state)
    assert result.status == 200
    assert result.body == f'{{"cuenta_id":"{account.account_id}","saldo":"{expected}"}}'


def test_transfer_is_provisional_and_does_not_mutate_state():
    state = TemporaryState()
    before = state.snapshot()
    result = dispatch("TRANSFER;missing;also-missing;not-a-number;00", state)
    assert (result.status, result.body) == (503, "aún no disponible")
    assert state.snapshot() == before


def test_deposit_and_annul_are_idempotent():
    state = TemporaryState()
    account = state.create_account("A")
    deposit = dispatch(f"DEPOSITO;{account.account_id};1;00", state)
    assert deposit.body == '{"status":"recieved","operacionId":"OP-0001"}'
    assert dispatch("ANULA;OP-0001;00", state).body == '{"ok":true,"anulada":"OP-0001"}'
    assert dispatch("ANULA;OP-0001;00", state).body == '{"ok":false,"motivo":"ya anulada"}'


def test_documented_twenty_digit_deposit_is_rejected_without_mutation():
    state = TemporaryState()
    account = state.create_account("A")
    before = state.snapshot()

    result = dispatch(f"DEPOSITO;{account.account_id};99999999999999999999;00", state)

    assert (result.status, result.body) == (400, '{"error":"E303","mensaje":"monto inválido"}')
    assert state.snapshot() == before
    accepted = dispatch(f"DEPOSITO;{account.account_id};1000000000;00", state)
    assert (accepted.status, accepted.body) == (200, '{"status":"recieved","operacionId":"OP-0001"}')


def test_documented_twenty_digit_deposit_is_validated_before_account_lookup():
    state = TemporaryState()
    result = dispatch("DEPOSITO;missing;99999999999999999999;00", state)
    assert (result.status, result.body) == (400, '{"error":"E303","mensaje":"monto inválido"}')
