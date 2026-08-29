# Bounce Data Should Pick the Channel: Email OTP or SMS for Support-Desk 2FA Login

Pick the OTP channel per account from your own suppression list instead of choosing one channel for the whole product. If a mailbox has already hard-bounced, email OTP will never log that person in, and SMS is the only path left that still reaches them. For a customer support SaaS the deciding constraint is integration effort rather than security or latency: the product already runs a bounce pipeline for ticket notifications, so email OTP inherits a suppression store, a classifier and an audit trail that exist today, while an SMS-first login asks the team to build a second delivery-failure taxonomy from scratch.

That's the whole decision.

The rest of this note is the part that usually gets skipped — the invariants that keep the rule honest, the failure the suppression list creates all by itself, and the option I'd reject.

## A deleted mailbox becomes a login outage nobody can see

A support desk sends a lot of mail to addresses it does not control, and some of those addresses die. An agent leaves a customer's company, IT deletes the mailbox, and the next message comes back as SMTP 550 with the enhanced status code 5.1.1 — class 5 for permanent, subject 1 for addressing, detail 1 for a bad destination mailbox (RFC 3463). Any pipeline worth running writes that address to a suppression list immediately, because repeatedly hammering dead mailboxes is one of the fastest ways to teach a mailbox provider that your domain sends garbage. So far this is ordinary transactional email hygiene. Then someone routes login codes through the same sender, the same domain and the same suppression check, and the list built to protect sending reputation starts quietly eating the one message a user is actively waiting for. The admin re-invites that departed agent, the invite is dropped before it reaches the wire, and the ticket says "I never get the code." Nobody on the support side can see why, because the drop happened in a component the login flow doesn't report on.

SMS has the mirror version of that problem, and it's harder to instrument. There's no DSN for text messages. You get a delivery receipt whose granularity depends on the route, and an unallocated or ported number can be accepted upstream and simply never produce a positive receipt. Email fails loudly, in a format standardized since 2003; SMS fails quietly, in a format that varies by carrier path.

That asymmetry is the real content of this decision. One channel hands you a machine-readable reason you can act on; the other hands you an absence.

## Should a support desk send 2FA login codes by SMS or email when deliverability is the deciding constraint?

Send them by email while the address is clean, and fall back to a verified phone number the moment your own bounce data condemns that address. The invariants matter more than the ranking.

The login path reads suppression state before issuing a challenge, never after. A permanent addressing failure on a login message suppresses the address *and* flags the account as needing a channel change, so a human sees a state rather than a silence. Transient 4.x.x results retry and never suppress. Delivery events update support and analytics records only — they can't mark a challenge verified, extend its lifetime, or trigger a second channel behind the user's back. And opens are not evidence of anything: Apple's Mail Privacy Protection loads remote content in a way that makes an open pixel useless as proof that a person saw a code, which is exactly why it must never be wired into an authentication decision.

Two things this design does not claim. Neither channel is phishing-resistant, because both deliver a secret the user can be talked into reading aloud; NIST SP 800-63B classes out-of-band authentication over the public telephone network as a restricted authenticator, since numbers can be ported or swapped. Administrative accounts and destructive actions in a support desk — mass ticket deletion, exporting a customer's conversation history — deserve an authenticator that isn't a shareable code at all.

On latency I'll be honest about the limits of my own evidence. Greylisting deliberately defers a first attempt with a temporary failure (RFC 6647), so a mailbox that has never seen your login sender can add minutes on the very first code and seconds forever after, while carrier paths vary by country in ways no public benchmark generalizes. Measure your own tenants, split by country and channel, and treat anyone's global numbers — including a number I could put in this paragraph — as marketing until you reproduce it.

## Three ways to wire the fallback, and the integration cost of each

| Wiring | Integration effort | Failure signal you get | Where it breaks |
|---|---|---|---|
| Email OTP on the existing bounce pipeline | Lowest: reuse the classifier, suppression store and audit trail already in production | DSNs plus RFC 3463 enhanced status codes | The suppression list silently drops codes unless the login path reads it first |
| SMS OTP as the only channel | A second delivery-failure taxonomy, number validation at capture, per-country spend caps | Carrier delivery receipts, route-dependent | Ported or unallocated numbers; artificially inflated traffic against your issuance endpoint |
| Suppression-driven per-account choice | Existing email pipeline plus a thin SMS adapter behind one interface | Both, normalized into one internal enum | Needs a verified phone on file *before* the address goes bad |
| Authenticator app instead of codes | Separate enrollment and recovery UX; no delivery at all | None needed | Device loss pushes everyone back onto the recovery path you were trying to avoid |

The table is a boundary check, not a scorecard. Run the same expiry policy, attempt accounting and recovery cases through each row before you believe any of it, because the row that looks cheapest on a slide is usually the one whose recovery flow you haven't designed yet.

## Bounce classification and channel choice in one screen of code

The critical path is small enough to fit in one screen, which is the point: the expensive part is the pipeline you already own, not this logic.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    BLOCKED = "blocked"          # no usable destination; show recovery, not "check your inbox"


class Verdict(str, Enum):
    RETRY = "retry"              # transient, try the same address again later
    SUPPRESS = "suppress"        # permanent addressing failure, stop sending
    REVIEW = "review"            # policy or reputation, a human fixes the sender


@dataclass(frozen=True)
class Recipient:
    email_suppressed_at: str | None      # set by the bounce pipeline, never by the login flow
    phone_e164: str | None               # E.164, verified at capture
    phone_verified: bool


def classify(enhanced_status: str) -> Verdict:
    """Map an RFC 3463 enhanced status code to what the login path may do next."""
    parts = enhanced_status.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return Verdict.REVIEW
    status_class, subject = parts[0], parts[1]
    if status_class == "4":
        return Verdict.RETRY
    if status_class != "5":
        return Verdict.REVIEW
    if subject == "1":
        return Verdict.SUPPRESS          # 5.1.x: the address itself is wrong
    if subject == "2":
        return Verdict.RETRY             # 5.2.2 full mailbox: worth one more attempt
    return Verdict.REVIEW                # 5.7.x: policy, alignment, reputation


def choose_channel(who: Recipient) -> Channel:
    if who.email_suppressed_at is None:
        return Channel.EMAIL
    if who.phone_e164 and who.phone_verified:
        return Channel.SMS
    return Channel.BLOCKED


if __name__ == "__main__":
    assert classify("5.1.1") is Verdict.SUPPRESS
    assert classify("4.4.1") is Verdict.RETRY
    assert classify("5.7.1") is Verdict.REVIEW

    departed_agent = Recipient(
        email_suppressed_at="2026-02-11T09:14:00Z",
        phone_e164="+15550100",
        phone_verified=True,
    )
    assert choose_channel(departed_agent) is Channel.SMS
    print(choose_channel(departed_agent).value)
```

What this snippet deliberately leaves out is as important as what it does. Attempt accounting, expiry after 10 minutes, one-time consumption of a successful code, and issuance limits per account and per destination all live in storage transitions, not in a classifier. Keep the transport behind a single interface with two adapters, so the SMS side stays an adapter rather than a parallel universe of retry logic; that's the shape that keeps integration effort proportional to the fallback's actual usage, which for a desktop-bound support tenant is a small minority of logins.

Operationally, watch the suppression list's growth rate rather than its size. A sudden spike in permanent failures right after a template or sender change is almost never a wave of deleted mailboxes — it's an authentication or policy problem on your side, which is where DMARC aggregate reports (RFC 7489) earn their keep. Give login mail its own subdomain so a rough month for ticket notifications doesn't drag the login sender's reputation with it, keep one seeded address per environment that always hard-bounces so the classifier gets exercised in CI, record issued, accepted, delivered, submitted and verified as five separate timestamps, and cap SMS issuance per account, per number and per country so an abusive script can't turn your login screen into someone else's revenue.

Agents need a view of delivery state. They must never see the code.

## What I rejected: SMS-first for every tenant, and when that flips

SMS-first for everyone, with email as a decorative fallback. It's tempting because carrier delivery feels immediate and because nobody has to think about DKIM alignment again. The catch is that it inverts the effort argument: you'd operate a channel whose failures arrive as route-specific receipts, add number lifecycle handling — porting, reassignment, corporate lines that vanish with the employee — and take on per-country cost exposure, all to protect a login flow whose users are already sitting in a browser next to their mailbox. Worse, it doesn't remove the suppression problem; it just moves it somewhere with less standardization and no equivalent of an enhanced status code.

Stick with SMS-first when the mailbox is not the account anchor, which is a real situation rather than a hypothetical: consumer marketplaces and field-service tools where accounts are created against a phone number and many users have no work mailbox at all. In that world the phone is the identity, and email is the fallback with the weaker data. This piece is not suitable as a template for those products, and honestly the recovery design there deserves its own decision record rather than a paragraph at the end of mine.

The general practice that survives both worlds is smaller than the channel debate: know which destinations your own data has already condemned, read that state before you issue a code, and never let a reputation-protection mechanism fail an authentication silently.

## References

- RFC 7489, Domain-based Message Authentication, Reporting, and Conformance (DMARC): https://datatracker.ietf.org/doc/html/rfc7489
- RFC 3463, Enhanced Mail System Status Codes: https://datatracker.ietf.org/doc/html/rfc3463
- RFC 3464, An Extensible Message Format for Delivery Status Notifications: https://datatracker.ietf.org/doc/html/rfc3464
- RFC 6647, Email Greylisting: An Applicability Statement for SMTP: https://datatracker.ietf.org/doc/html/rfc6647
- NIST SP 800-63B, Digital Identity Guidelines — Authentication and Lifecycle Management: https://pages.nist.gov/800-63-3/sp800-63b.html
- ITU-T Recommendation E.164, The international public telecommunication numbering plan: https://www.itu.int/rec/T-REC-E.164
- Apple, Use Mail Privacy Protection on iPhone: https://support.apple.com/guide/iphone/use-mail-privacy-protection-iphf084865c7/ios
