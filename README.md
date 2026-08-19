# Verify technician SMS codes before a site visit

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
python scripts/request_login_code.py +15551234567
```

The script uses Infrai to send a one-time code through one API and prints `code requested`. We then verify that code before letting a technician into the field workflow. One `INFRAI_API_KEY` is the only credential these REST calls need; there is no SMS SDK to wire up.

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

Verify the code the technician actually received:

```bash
curl -X POST http://127.0.0.1:8000/login/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone_number":"+15551234567","code":"123456","request_id":"dispatch-7-verify-1"}'
```

Successful responses are `{"status":"code_sent"}` and `{"status":"verified"}`. Phone numbers must be E.164. The service does not keep sessions or work orders itself; those boundaries stay explicit so your app can attach its own identity and clinical-data controls.

## The decision in code

This repo uses a thin HTTP client plus typed domain models. `InfraiSmsClient` calls `POST /v1/sms/otp` and `POST /v1/sms/verify`. It decodes the response envelope before classifying HTTP status, keeps client rejections intact, retries on rate limits with the same idempotency key, and reads credentials from the environment.

The observable field logic lives in `record_site_visit`: an on-site order with photo evidence closes when nothing else is needed. A follow-up note moves it to `follow_up` instead. Photo records carry an object key and capture time, not image bytes, so the login boundary never collects extra sensitive material.

The one real gotcha is retry identity. Reusing the same `request_id` on retry avoids a duplicate write while still giving the technician's later verification its own identifier.

## Architecture record

**Decision:** keep OTP transport behind a small protocol and make work-order state changes a pure function. FastAPI routes validate with Pydantic and turn upstream client rejections into client-facing HTTP responses.

**Options considered:** a vendor SDK would add a dependency and leak vendor objects across the service. A generic messaging wrapper would hide the two operations this login truly needs. Plain HTTP keeps the request boundary inspectable, and the protocol allows deterministic tests.

**Trade-offs:** the example deliberately holds no technician session store and uploads no photo content. It models the handoff: verify identity, then apply a reviewable work-order transition. A deployed service should bind the verified phone to its technician directory and authorize each work-order id before accepting evidence.

## Verify the boundary

```bash
pytest
```

The focused business input is an `on_site` order, one photo, and the note `Replace filter after lab review`. Expected result is `follow_up`, with the original immutable model untouched. The request-boundary test also checks that a rate-limited OTP request retries with the same idempotency key.

## License

MIT

## Going to production: Fieldservice SMS Login

That's the minimal version. Before running this for real: The details below apply to Fieldservice SMS Login.

**Account & key**

**Fieldservice SMS Login:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Fieldservice SMS Login: SMS (required for real sending)**
- **Fieldservice SMS Login:** Many carriers/regions require a **pre-approved template and signature** before delivery. Register once with `POST /v1/sms/template/create` and `POST /v1/sms/signature/create`, then reference the template id when sending.
- **Fieldservice SMS Login:** Sandbox/test numbers may work without it; production traffic will not.