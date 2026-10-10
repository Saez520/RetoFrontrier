"""Cliente del original: auth, captura, ritmo, presupuesto, corte y reintentos."""

import unittest
from datetime import datetime, timedelta, timezone

from probe_harness import models
from probe_harness.oracle_client import (
    OracleClient,
    StopRequested,
    TransportError,
    TransportResponse,
)

CUTOFF = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now):
        self.now = now
        self.mono = 0.0

    def monotonic(self):
        return self.mono

    def now_utc(self):
        return self.now

    def advance(self, seconds):
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_spec(**overrides):
    data = dict(
        case_id="E1-06",
        method="POST",
        path="/msg",
        hypothesis="h",
        axis="E1",
        body_raw='{"m":"PING;64"}',
        content_type="application/json",
    )
    data.update(overrides)
    return models.RequestSpec(**data)


def make_client(transport, clock=None, **kwargs):
    clock = clock or FakeClock(datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc))
    sleeps = []
    kwargs.setdefault("id_factory", iter([f"id{i}" for i in range(20)]).__next__)
    client = OracleClient(
        transport,
        clock,
        sleeper=sleeps.append,
        base_url="https://example.test",
        token="secret-token",
        cutoff=CUTOFF,
        **kwargs,
    )
    client._fake_sleeps = sleeps
    return client


class AuthTest(unittest.TestCase):
    def test_valid_bearer_sent(self):
        transport = FakeTransport([TransportResponse(200, {}, b"{}")])
        client = make_client(transport)
        client.send(make_spec(), '{"m":"PING;64"}', seq="E1")
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], "Bearer secret-token")

    def test_missing_auth_omits_header(self):
        transport = FakeTransport([TransportResponse(200, {}, b"{}")])
        client = make_client(transport)
        client.send(make_spec(auth_mode=models.AUTH_MISSING), None, seq="E1")
        self.assertNotIn("Authorization", transport.calls[0]["headers"])

    def test_invalid_auth_uses_literal(self):
        transport = FakeTransport([TransportResponse(200, {}, b"{}")])
        client = make_client(transport)
        client.send(make_spec(auth_mode=models.AUTH_INVALID), None, seq="E1")
        self.assertEqual(
            transport.calls[0]["headers"]["Authorization"], "Bearer probe-invalid-token"
        )

    def test_url_from_base_and_path(self):
        transport = FakeTransport([TransportResponse(200, {}, b"{}")])
        client = make_client(transport)
        client.send(make_spec(path="/health", method="GET"), None, seq="E1")
        self.assertEqual(transport.calls[0]["url"], "https://example.test/health")


class CaptureTest(unittest.TestCase):
    def test_captures_status_xreq_and_body(self):
        transport = FakeTransport(
            [TransportResponse(201, {"X-Req": "42", "Content-Type": "application/json"}, b'{"cuentaId":"AC-0001"}')]
        )
        client = make_client(transport)
        result = client.send(make_spec(), '{"m":"PING;64"}', seq="E1")[-1]
        self.assertEqual(result.status, 201)
        self.assertEqual(result.x_req, "42")
        self.assertEqual(result.response_text, '{"cuentaId":"AC-0001"}')
        self.assertFalse(result.infra)


class PacingBudgetCutoffTest(unittest.TestCase):
    def test_minimum_interval_between_sends(self):
        transport = FakeTransport(
            [TransportResponse(200, {}, b"{}"), TransportResponse(200, {}, b"{}")]
        )
        client = make_client(transport)
        client.send(make_spec(), "{}", seq="E1")
        client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(client._fake_sleeps, [0.125])

    def test_cutoff_stops_before_transport(self):
        clock = FakeClock(CUTOFF)
        transport = FakeTransport([])
        client = make_client(transport, clock=clock)
        with self.assertRaises(StopRequested) as ctx:
            client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(ctx.exception.reason.value, "cutoff")
        self.assertEqual(transport.calls, [])

    def test_budget_stops_before_transport(self):
        transport = FakeTransport([])
        client = make_client(transport, max_calls=0)
        with self.assertRaises(StopRequested) as ctx:
            client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(ctx.exception.reason.value, "budget")
        self.assertEqual(transport.calls, [])

    def test_call_counter_accumulates(self):
        transport = FakeTransport([TransportResponse(200, {}, b"{}")] * 3)
        client = make_client(transport)
        client.send(make_spec(), "{}", seq="E1")
        client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(client.calls_made, 2)


class RetryTest(unittest.TestCase):
    def test_infra_triggers_two_retries_then_success(self):
        transport = FakeTransport(
            [
                TransportResponse(429, {"X-Frontier-Infra": "rate-limit"}, b"infra"),
                TransportResponse(429, {"X-Frontier-Infra": "rate-limit"}, b"infra"),
                TransportResponse(200, {}, b"{}"),
            ]
        )
        client = make_client(transport)
        observed = []

        class Hooks:
            def before_send(self, meta):
                observed.append((meta.retry_index, meta.attempt_of))

            def after_send(self, result, meta):
                pass

        results = client.send(make_spec(), "{}", seq="E1", hooks=Hooks())
        self.assertEqual(len(results), 3)
        first_id = results[0].attempt_id
        self.assertEqual([o[0] for o in observed], [0, 1, 2])
        self.assertEqual(observed[0][1], None)
        self.assertEqual(observed[1][1], first_id)
        self.assertEqual(observed[2][1], first_id)
        self.assertTrue(results[0].infra)
        self.assertTrue(results[1].infra)
        self.assertFalse(results[2].infra)
        waits = [s for s in client._fake_sleeps if s >= 1.0]
        self.assertEqual(waits, [1.0, 5.0])

    def test_infra_retries_are_bounded(self):
        transport = FakeTransport([TransportResponse(429, {"X-Frontier-Infra": "r"}, b"x")] * 3)
        client = make_client(transport)
        results = client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.infra for r in results))

    def test_transport_error_is_evidence_without_retry(self):
        transport = FakeTransport([TransportError("boom")])
        client = make_client(transport)
        results = client.send(make_spec(), "{}", seq="E1")
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].status)
        self.assertEqual(results[0].error, "boom")


if __name__ == "__main__":
    unittest.main()
