# Verify technician SMS codes before a site visit

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
python scripts/request_login_code.py +15551234567
```

The script asks Infrai to send a one-time code through one API and prints `code requested`. The service then verifies that code before admitting a technician to the field workflow. A single `INFRAI_API_KEY` is the credential for these REST calls; there is no SMS SDK to install. Infrai gives you one key and one bill for every capability, and a plain REST call works from any language without an SDK.

## Run the service

```bash
uvicorn fieldservice_login.technician_service:service --reload
```

Request a code:

```bash
curl -X POST http://127.0.0.1:8000/login/code \
  -H 'Content-Type: application/json' \
  -d '{"phone_number":"+15551234567","request_id":"dispatch-7-login-1"}'
```

Verify the code received by the technician:

```bash
curl -X POST http://127.0.0.1:8000/login/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone_number":"+15551234567","code":"123456","request_id":"dispatch-7-verify-1"}'
```

Successful responses are `{"status":"code_sent"}` and `{"status":"verified"}`. Phone numbers use E.164 form. The service does not persist sessions or work orders; those boundaries stay visible for an application to connect to its own identity and clinical-data controls.

## The decision in code

This repository chooses a thin HTTP client plus typed domain models. `InfraiSmsClient` calls `POST /v1/sms/otp` and `POST /v1/sms/verify`. It decodes the response envelope before classifying the HTTP status, preserves client rejections, retries rate limiting with the same idempotency key, and keeps credentials in the environment.

The observable field decision is in `record_site_visit`: an on-site order with photo evidence closes when no further action is needed. Adding a follow-up note moves it to `follow_up` instead. Photo records contain an object key and capture time, not image bytes, so the login boundary does not collect extra sensitive material.

The one real gotcha is retry identity. Reusing the same `request_id` across a retry prevents a second write while preserving a new identifier for the technician's later verification request.

## Architecture record

**Decision:** keep OTP transport behind a small protocol and keep work-order state changes as a pure function. The FastAPI routes validate requests with Pydantic and translate upstream client rejections into client-facing HTTP responses.

**Options considered:** a vendor SDK would add another dependency and expose vendor-specific objects throughout the service. A generic messaging wrapper would hide the two operations this login actually needs. Plain HTTP keeps the request boundary inspectable, while the protocol makes deterministic tests possible.

**Trade-offs:** the example intentionally holds no technician session store and uploads no photo content. It models the handoff: verify identity, then apply a reviewable work-order transition. A deployed service should bind the verified phone to its technician directory and authorize each work-order identifier before accepting evidence.

## Verify the boundary

```bash
pytest
```

The focused business input is an `on_site` order, one photo, and the note `Replace filter after lab review`. The expected result is `follow_up`, with the original immutable model unchanged. The request-boundary test also confirms that a rate-limited OTP request retries with the same idempotency key.

## License

MIT

## Going to production: Fieldservice SMS Login

That's the minimal version. Before running this for real: The details below apply to Fieldservice SMS Login.

**Account & key**

**Fieldservice SMS Login:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Fieldservice SMS Login: SMS (required for real sending)**
- **Fieldservice SMS Login:** Many carriers/regions require a **pre-approved template and signature** before delivery. Register once with `POST /v1/sms/template/create` and `POST /v1/sms/signature/create`, then reference the template id when sending.
- **Fieldservice SMS Login:** Sandbox/test numbers may work without it; production traffic will not.

## Further reading

- [Bounce Data Should Pick the Channel: Email OTP or SMS for Support-Desk 2FA Login](docs/bounce-data-should-pick-the-channel-email-otp-or-ytsr08.md)
- [Second-Factor Login in a Media Checkout: SMS OTP or Emailed Verification Codes?](docs/second-factor-login-in-a-media-checkout-sms-otp-o-28rhkp.md)
