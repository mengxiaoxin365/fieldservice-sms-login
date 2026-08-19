import httpx

from fieldservice_login.infrai_sms import InfraiSmsClient


def test_otp_request_retries_429_and_keeps_idempotency_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"ok": False, "data": None, "error": {}},
            )
        return httpx.Response(200, json={"ok": True, "data": {"status": "sent"}})

    client = InfraiSmsClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = client.request_code("+15551234567", "login-req-001")

    assert result == {"status": "sent"}
    assert len(requests) == 2
    assert {request.headers["Idempotency-Key"] for request in requests} == {
        "login-req-001"
    }
    assert all(request.method == "POST" for request in requests)
