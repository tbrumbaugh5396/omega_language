# Verification — what a person checks, and signs

*To the client. The tests prove the code; verification proves the product.*

A green test suite says the code does what its tests say. It does not say
the page is readable, the button is where a thumb expects it, or the order
confirmation email reads like your brand. That is verification: a person,
a checklist, and a signature, at each gate.

## When verification happens

| Gate | Who verifies | Against what |
|---|---|---|
| Round 1 (homepage) | Us, then you | The art direction and the homepage requirement |
| Round 2 (full system) | Us, then you | The signed requirements, line by line |
| Pre-launch | Us | The [launch checklist](../09-launch/launch-checklist.md) |
| Launch day | Us, with you watching | The live system, real devices, real money |
| Every release after | Us | The change's own note and the smoke checks |

## How we verify a round

1. **Walk the requirements.** Every line of the signed requirement is
   opened on the preview and marked *done*, *partly*, or *not yet*, with a
   note. You receive this sheet with the round.
2. **Walk the journeys.** The five things a real person does — find a
   product, buy it, track it, ask for help, sign in — each done end to end
   on a phone, a tablet and a laptop.
3. **Read the words.** Every page, every email, every error message, read
   aloud once. Placeholder text, another client's copy, and "Lorem" are
   defects.
4. **Break it politely.** Wrong password, empty cart, expired code, a
   double-submitted form, back button mid-checkout. Each has to fail with a
   sentence, not a blank page.
5. **Check what it keeps.** A test order is placed and then found in every
   place it should appear — the order list, the stock, the customer's
   account, the accounts — and in no place it should not.

## Your part

Your feedback form for each round is the verification record from your
side. Mark what you checked, not only what you disliked: a form that says
*"checked the checkout on my phone, fine"* is as valuable as one that finds
a fault, because it tells us where not to look twice.

## Signing

A round is verified when both sheets — ours and yours — are complete and
the open items are either fixed or written into a change order. That
signature is the gate; nothing after it reopens the round.

## What verification is not

It does not replace the [tests](test-process.md), which run the same
checks thousands of times more patiently than any person. It catches what
tests cannot judge: whether the thing is right, not only whether it works.
