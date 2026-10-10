"""Estado temporal de cuentas y operaciones del servicio."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class Account:
    account_id: str
    name: str
    balance_cents: int = 0


@dataclass
class Operation:
    operation_id: str
    account_id: str
    amount_cents: int
    annulled: bool = False


class TemporaryState:
    """Estado privado por instancia, con mutaciones encapsuladas."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._operations: dict[str, Operation] = {}
        self._account_counter = 0
        self._operation_counter = 0

    def create_account(self, name: str) -> Account:
        self._account_counter += 1
        account = Account(f"AC-{self._account_counter:04d}", name)
        self._accounts[account.account_id] = account
        return deepcopy(account)

    def get_account(self, account_id: str) -> Account | None:
        account = self._accounts.get(account_id)
        return deepcopy(account) if account else None

    def deposit(self, account_id: str, amount_cents: int) -> Operation | None:
        account = self._accounts.get(account_id)
        if account is None:
            return None
        self._operation_counter += 1
        operation = Operation(f"OP-{self._operation_counter:04d}", account_id, amount_cents)
        account.balance_cents += amount_cents
        self._operations[operation.operation_id] = operation
        return deepcopy(operation)

    def annul(self, operation_id: str) -> tuple[bool, bool]:
        operation = self._operations.get(operation_id)
        if operation is None:
            return False, False
        if operation.annulled:
            return True, False
        self._accounts[operation.account_id].balance_cents -= operation.amount_cents
        operation.annulled = True
        return True, True

    def snapshot(self) -> dict[str, object]:
        return deepcopy({
            "accounts": self._accounts,
            "operations": self._operations,
            "account_counter": self._account_counter,
            "operation_counter": self._operation_counter,
        })
