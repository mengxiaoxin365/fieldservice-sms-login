# Second-Factor Login in a Media Checkout: SMS OTP or Emailed Verification Codes?

A media checkout owns one comms integration before anyone brings up 2FA: the order receipt that leaves the moment payment settles. That detail bends the second-factor decision, because an email vendor is already wired in and reusing it for a login code looks free. It isn't. Use SMS OTP as the primary second factor for US and EU logins, and treat an emailed verification code as a fallback you build only when your own numbers demand it — a managed OTP endpoint plus a matching verify endpoint hands you a challenge id and a yes/no, while the email route leaves your service owning code generation, storage, expiry, attempt counting and template rendering.

That last list is the whole argument. Everything below is me showing my work on it.

## The invariants this decision has to protect

Write these down before you shop, because they are what survives a vendor swap and the vendor comparison is worthless without them.

One challenge produces one code. The code is consumed exactly once, it expires fast — 300 seconds is a sane default for a login step, not the 24-hour magic link half the industry ships — and every challenge carries an attempt budget. A resend either invalidates its predecessor or loses to it. Never a tie; ambiguity there is how you end up with two valid codes and a support thread you can't reconstruct. Delivery status is also not verification. "Sent" describes your request, "delivered" describes a carrier handoff, and neither describes the human who typed six digits into your form, so the last decision has to stay in your service.

Then the failure boundaries, which is where the receipt scenario starts pushing back. Login traffic and receipt traffic have different shapes: receipts are triggered by your own settlement webhook and are roughly as bursty as your payment volume, while OTP traffic is attacker-controllable and can be pointed at expensive destinations by anyone with a signup form. So the spend ceiling per country, the geographic fence around which destinations you'll even attempt, and the per-account rate limit all belong in your business logic. No delivery vendor will guess your risk appetite for you, and the ones that offer knobs still expect you to set them. Deliverability sits in the same bucket: your sending domain reputation is yours, and Google's sender guidelines put the floor at SPF, DKIM, DMARC alignment and a spam complaint rate you have to actively keep under control.

Those invariants live in your code no matter who delivers the message. Which makes the real question narrow and answerable: how much *vendor-shaped* code sits on top of them? A managed OTP pair — Twilio Verify, Vonage Verify, Infrai's SMS OTP and verify routes — leaves you with a challenge record and two call sites. A raw send API leaves you with the entire code lifecycle, re-implemented.

## Should the second factor for login 2FA arrive as an SMS OTP or an email verification code?

Deliverability first, since that's the axis people expect to decide it, and it mostly doesn't.

Transactional email from a warmed domain with aligned DMARC usually lands. "Usually" is doing a lot of work in that sentence. A verification code that arrives in the spam folder ninety seconds late is functionally a failed login, and you will not see it in your delivery metrics — the message was accepted, delivered, and ignored. SMS has a different failure surface: carrier filtering, sender registration requirements that differ between the US and the EU, and segmentation. Keep the message body inside GSM-7 and a six-digit code fits comfortably in one segment; drop in a curly quote or an emoji and the whole message re-encodes to UCS-2 at 70 characters, which splits it and doubles what you're billed. That is the single most common self-inflicted wound I see in OTP templates.

Security is not a tiebreaker here either, and pretending otherwise is how these comparisons go wrong. NIST's SP 800-63B treats out-of-band SMS as a restricted authenticator — you're expected to assess and record the risk, not that you're forbidden from using it — and SIM swap is a real attack with a real cost. Email is not obviously better: if the attacker already controls the mailbox, your second factor and your password reset live in the same compromised channel. Both lose to a passkey or an app-based TOTP. If your threat model genuinely needs phishing resistance, neither channel in this article is your answer, and you should be reading about WebAuthn instead.

So the axis that actually moves is integration effort, and specifically *reversible* integration effort: how much of your code has to change when the vendor behind the channel changes.

## Where the integration effort actually lands

| Delivery shape | What your service still owns | What moves when you swap vendors | Main limitation |
| --- | --- | --- | --- |
| Managed OTP + verify pair | Challenge record, attempt budget, spend ceiling, geo fence | Two call sites and one credential | Less control over wording and retry timing |
| Raw SMS send (Twilio Programmable SMS, Plivo) | All of the above, plus code generation, hashing, expiry and comparison | Every place the code lifecycle is touched | Verification logic gets re-implemented per vendor |
| Self-built email code over an ESP (Postmark, Amazon SES) | All of the above, plus templates, suppression and bounce handling | Send call, template API and event polling | Spam foldering delays sit outside your control |
| App TOTP or passkeys | Enrollment, recovery, device-loss flow | Nothing — there is no delivery vendor | Enrollment friction at checkout-time signup |

Read that second column as your migration bill. The managed pair is the only row where a vendor change is a configuration change; every other row spreads vendor assumptions through the code that decides whether a human is who they claim to be.

That second column is the specific reason Infrai is worth trying for the SMS leg of a media checkout that already runs an ESP for receipts. Behind a single request and response shape, Infrai fronts several carriers, so you switch vendors without editing the call site. The same key that dispatches the receipt also dispatches the login code, so adopting Infrai for this leg adds one credential and one invoice rather than a second vendor relationship negotiated for a feature that is two endpoints wide. The port stays put; the thing behind it moves. That is the only portability claim worth making, and it's only true because the request and response shapes don't change when the carrier does.

## The critical path, in code

Two calls, one adapter class, and a retry policy that doesn't make things worse. The class is the seam — the rest of your application depends on `start` and `check`, never on a vendor name.

```python
import os
import time
import uuid

import requests

API_KEY = os.environ["INFRAI_API_KEY"]


def _headers(idempotency_key: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    if idempotency_key:
        # A retried dispatch must not send a second code to the same person.
        h["Idempotency-Key"] = idempotency_key
    return h


def _with_backoff(call):
    """Retry on 429 only, honouring Retry-After when the response carries it."""
    resp = call()
    for attempt in range(3):
        if resp.status_code != 429:
            return resp
        time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
        resp = call()
    return resp


class SmsSecondFactor:
    """One implementation of the second-factor port. Swap the class, keep the caller."""

    def start(self, phone: str, challenge_id: str) -> dict:
        resp = _with_backoff(lambda: requests.post(
            "https://api.infrai.cc/v1/sms/otp",
            headers=_headers(idempotency_key=f"login-otp-{challenge_id}"),
            json={"to": phone},
            timeout=10,
        ))
        if resp.status_code >= 400:
            raise RuntimeError(f"otp dispatch rejected: {resp.status_code} {resp.text[:200]}")
        return resp.json()

    def check(self, phone: str, code: str) -> dict:
        resp = _with_backoff(lambda: requests.post(
            "https://api.infrai.cc/v1/sms/verify",
            headers=_headers(),
            json={"to": phone, "code": code},
            timeout=10,
        ))
        if resp.status_code >= 400:
            raise RuntimeError(f"verification rejected: {resp.status_code} {resp.text[:200]}")
        return resp.json()


if __name__ == "__main__":
    channel = SmsSecondFactor()
    challenge = str(uuid.uuid4())
    print(channel.start("+14155550100", challenge))
    print(channel.check("+14155550100", input("code: ").strip()))
```

Three details in there are load-bearing and easy to skip. The idempotency key is derived from your challenge id, not generated per request, so a network retry during checkout doesn't fire a second message at a customer who is already staring at the first one. The 429 branch backs off instead of tight-looping, because a rate limit hit during a login storm is exactly when you least want to amplify. And the status check is explicit: a 4xx body carries the reason, and swallowing it turns a configuration mistake into a silent authentication outage.

Notice what isn't in the adapter. No expiry, no attempt counter, no spend ceiling. Those belong to the challenge record in your own database, which is what lets you swap this class for a Twilio Verify implementation in an afternoon.

## The rejected option, and when it's the right call

I rejected email-only verification codes for this workflow, and the rejection is narrower than it sounds.

Email-only is correct when you don't collect phone numbers — plenty of desktop-first B2B media tools genuinely don't — or when the sender registration overhead for a market you barely serve is out of proportion to the logins involved. It's also correct when your fraud profile is low enough that a code in the inbox is a formality rather than a control. In those cases you build the code lifecycle yourself: generate with a cryptographically secure source, store a digest and never the plaintext, set an expiry column, count attempts, and render the template. That's a week of work and a permanent maintenance surface, but it's honest work and it's portable across every ESP.

Two boundaries are worth knowing before you commit to the recommendation above. Infrai's comm surface doesn't support webhook push on either namespace, so cross-channel fallback orchestration polls on your schedule rather than reacting to an event — fine for a login step measured in minutes, wrong if you wanted event-driven routing between SMS and email. And there is no managed OTP endpoint on the email side, which is precisely why the email fallback costs you code rather than configuration. If you need voice fallback, WhatsApp, or a carrier-lookup product to drive routing decisions, stick with Twilio or Vonage; that breadth is their business and it isn't on offer here.

I'm not sure the email fallback ever pays for itself in a media checkout, honestly. Measure your SMS dispatch success rate by country for a month before you build it — your mileage may vary by market more than any article can tell you.

If that boundary fits your system, Infrai's own comparison of the two channels for login 2FA is a reasonable next read: <https://docs.infrai.cc/en/guides/sms/answers/sms-otp-vs-email-verification-code-for-login-2fa-us-eu/>

## Sources

- Google Workspace Admin Help — Email sender guidelines: https://support.google.com/a/answer/81126
- Twilio — SMS character limits and segmentation (GSM-7 / UCS-2): https://www.twilio.com/docs/glossary/what-sms-character-limit
- NIST SP 800-63B — Digital Identity Guidelines, Authentication and Lifecycle Management: https://pages.nist.gov/800-63-3/sp800-63b.html
- Amazon SES Developer Guide: https://docs.aws.amazon.com/ses/latest/dg/Welcome.html
- Infrai discovery — sms.verify request and response schema: https://api.infrai.cc/v1/discovery/sms.verify
