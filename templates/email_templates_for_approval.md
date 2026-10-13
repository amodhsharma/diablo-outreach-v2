# Outreach email template

Two first-email templates, both for every Location and Channel:

- **Template 1** (`templates/template_1.json`), agreed by Ariel on 12 Oct 2026, shown first below.
- **Template 2** (`templates/template_2.json`), the team's version, at the end of this page. **The
  first email currently uses template 2.**

Which file is used is set in `config/settings.yaml` under `send.templates`. The reminder is
`templates/follow_up.json`. This page shows them in plain words.

## How an email is put together

| Part | Where it comes from |
|---|---|
| Subject | Fixed: "Partnering to establish Diablo Sugar Free in the {{market_short}} sugar free snacks landscape", where {{market_short}} is the first part of the Location (Dublin for "Dublin, Ireland") |
| Personal line | The outreach-mail-writing skill, per person (its own paragraph after the introduction) |
| Partner type | The company's Channel in one word: distributor, wholesaler, retailer, online seller |
| Catalogue link | `send.catalogue_link` in `config/settings.yaml` (a dummy link until the catalogue is live) |
| Signature | `send.signature` in `config/settings.yaml`: Joshua, Initial Outreach Team. Shown after "Best regards," as an indented block with a thin grey bar on the left, like a quote |
| Footer | Fixed, with the opt-out and privacy notice |

The sender name shown in the inbox ("Joshua") is each mailbox's sender name in Instantly, Email
Accounts. It is set there, not here.

## First email

> Subject: Partnering to establish Diablo Sugar Free in the {{market_short}} sugar free snacks landscape
>
> Hi {{firstName}},
>
> I hope this email finds you well.
>
> I am reaching out from Diablo Sugar Free, Europe's largest no added sugar and sugar free snacks
> brand, based in the United Kingdom. We have been closely following the growth of the sugar free
> sector in {{market}}, and your reputation as a premier {{partner_type}} makes you an ideal partner
> for our international expansion.
>
> {{personal_line}}
>
> We believe Diablo Sugar Free will resonate strongly with your customers because:
>
> - Market fit: our 117+ products, sweetened with stevia and inulin and never aspartame, directly
>   address the rising consumer demand for sugar free and lower sugar treats in your region.
> - Proven track record: we sell in more than 124 countries and are listed with Carrefour, Lidl,
>   Tesco and Holland & Barrett. We are fully equipped to support international logistics.
> - Marketing support: we don't just sell products; we build brands. We provide robust marketing
>   budgets, localised digital campaigns and in-store promotional assets to ensure a successful
>   launch.
>
> You can view our latest product catalogue here: {{catalogue_link}}. We would also be happy to send
> you samples.
>
> Are you open to a brief 10-minute introductory call next week to discuss how we can introduce
> Diablo Sugar Free to your network? Please let me know what day and time works best for you. You
> can also book a time directly here: {{booking_link}}
>
> Thank you for your time and consideration.
>
> Best regards,
> Joshua
> Initial Outreach Team
> Diablo Sugar Free
> www.diablosugarfree.com
> XXXXXX (phone, placeholder)

## Reminder (rounds 2 and 3: one template, sent as a reply in the person's own thread; agreed 14 Oct 2026)

> Hi {{firstName}},
>
> In case our earlier note to your colleague [full name] did not reach the right desk, we wanted to
> share it with you as well.
>
> We wanted to follow up on our note about bringing Diablo Sugar Free to {{market}}. We would be
> glad to send you samples, along with our pricing and logistics details, so you can judge the fit
> for your customers.
>
> Would a brief 10-minute call with our outreach lead work for you at a time of your convenience?
>
> Best regards,
> Joshua
> Initial Outreach Team
> Diablo Sugar Free
> www.diablosugarfree.com
> XXXXXX (phone, placeholder)

The colleague sentence names the person at the same company who was emailed most recently before
this email and has not replied. A bounced person is never named, and nobody is named when the
company has no such colleague: the sentence is then left out. The name is filled in only when the
email is sent; it is never stored in GitHub. Round 3 uses the same template (the separate last
note was dropped on 14 Oct 2026).

## Footer (every email)

Grey (#888888), slightly smaller text (12px), under a thin full-width grey line (agreed 12 Oct 2026):

> ---
> [Diablo Sugar Free](https://www.diablosugarfree.com) (B Healthy Ltd, London)
> We found your business details in public and commercial sources. If you would rather not hear
> from us, reply "no thanks" and we will not contact you again.
>
> Privacy notice: [https://www.diablosugarfree.com/policies/privacy-policy](https://www.diablosugarfree.com/policies/privacy-policy)

"Diablo Sugar Free" links to the website and the privacy notice link is clickable. The reminder's
footer leaves out the "We found your business details..." sentence.

## Still to do

- Replace the dummy catalogue link once the 2026 catalogue is online.
- Replace the placeholder phone number XXXXXX (`send.signature.phone`) with Joshua's real number.
- The booking link (`send.booking_link`) is the placeholder "xxx" until Ariel gives the real link.
  Template 2 ends with "you can do it from the link below", so until a real web address is there,
  Send sends nothing and changes no campaign (it stops with a "booking link is missing" message).
  Template 1 simply leaves its "You can also book a time directly here" sentence out.

## Rules for the personal line (agreed 14 Oct 2026)

The personal line is its own paragraph, after the introduction. Each contact is given one of four
styles at random, so not every email reads the same. Every style is used about equally, and
people at the same company always get different styles. The parts in [brackets] are filled from
that company's own research; every other word is fixed.

- **A. Respect for their reach:** "We have great respect for the way your team [what they do and
  for whom]. With such established reach [across their channels], we would be honoured if you would
  consider whether a sugar free range could have a place in your portfolio."
- **B. Their track record:** "Your team's work in [a specific achievement from the research] speaks
  for itself. We would value the opportunity to present our sugar free range and to hear whether
  you feel it could sit alongside [the brands you already represent / the products you already
  offer]."
- **C. Their range:** "Your range, [from X to Y], reflects a careful choice of [brands or products]
  for [their market]. We would welcome the chance to present our sugar free range for your
  consideration, should you see a place for it."
- **D. Partnership:** "We hold your team in high regard for [a specific achievement or position
  from the research]. We would be grateful for the opportunity to discuss whether our sugar free
  range could be a worthwhile addition to your business."

The tone: we are pitching to them and they have the upper hand, so the line is respectful and
formal, proposes the idea and leaves the decision with them. It says "we", never "I" (the
email's opening sentence keeps "I", as it speaks for the single sender).

- Two sentences, 60 words or fewer; the company name at most once.
- Never: invented facts, numbers or names; casual words (fun, enjoy, lovely, love, chat,
  exciting); over-the-top praise (incredible, amazing, outstanding, wonderful, world-class);
  guesses about what they lack or have not considered; health claims or the words "diabetic",
  "diabetes" or "healthy"; exclamation marks.
- British English, no em dashes or en dashes, no Oxford commas, "sugar free" without a hyphen.

## Template 2 (in use for the first email from 13 Oct 2026; wording agreed 14 Oct 2026)

> Hi {{firstName}},
>
> I'm writing from the office of the Strategy Director at Diablo Sugar Free, where I look after
> international partners.
>
> By way of introduction, we are the largest sugar-free confectionery company in Europe. Chocolate
> bars and boxed chocolates, biscuits, wafers, sweets, spreads and jams, eleven categories in all.
> As you'll know, sugar-free carries a better margin than standard confectionery, because the
> shopper accepts a higher price point. We supply more than 126 countries and are listed with
> Carrefour, Lidl, Tesco and Holland & Barrett.
>
> {{personal_line}}
>
> Attaching a catalogue for your reference: {{catalogue_link}}
>
> We would be more than glad to set up a call between your team and our outreach or strategy team
> leads, so we can look at what the range would need to earn properly for your professional
> customers.
>
> Let us know what day and time suits your team's schedule. Or if you would want to set up a call
> directly, you can do it from the link below.
> {{booking_link}}
>
> Best regards,
> (signature and footer, the same as template 1)

Changed on 14 Oct 2026: the introduction now comes before the personal line; the sentence "We are
a UK brand and do not yet have a direct partner in ..." was removed; the catalogue, call and
booking sentences were reworded as above. The 126 countries figure stays as it is.

Which file is used is set in `config/settings.yaml` under `send.templates`. To go back to
`templates/template_1.json`, change that path; nothing else needs to change.
