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

## Reminder (round 2: sent as a reply in the person's own thread, see the README for timing)

> Hi {{firstName}},
>
> I wanted to follow up on my note from a few days ago about bringing Diablo Sugar Free to
> {{market}}. We would be glad to send you samples, along with our pricing and logistics details, so
> you can judge the fit for your customers.
>
> Would a brief 10-minute call next week work for you, or is there someone else on your team I
> should speak to?
>
> Best regards,
> Joshua
> Initial Outreach Team
> Diablo Sugar Free
> www.diablosugarfree.com
> XXXXXX (phone, placeholder)

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
- The Microsoft Bookings link (`send.booking_link`): until it is set, the "You can also book a time
  directly here" sentence is left out of the first email.

## Rules for the personal line

- One or two sentences, 50 words or fewer, starting with something true and specific the company
  does well, then why that makes it a fit for Diablo.
- Never: invented facts, numbers or names; empty flattery; health claims or the words "diabetic",
  "diabetes" or "healthy"; exclamation marks; the company name more than once.
- British English, no em dashes or en dashes, no Oxford commas.

## Template 2 (in use for the first email from 13 Oct 2026)

`templates/template_2.json` holds the team's version of the first email, with placeholders:
`{{firstName}}`, `{{personal_line}}` (written per company, starting "I thought I'd reach out as we
have noticed..."), `{{market_country}}` (e.g. "the Netherlands"), `{{catalogue_link}}` and the
booking link sentence. It ends with the same sign-off and privacy footer as the template above.

Which file is used is set in `config/settings.yaml` under `send.templates`. To go back to
`templates/template_1.json`, change that path; nothing else needs to change.

## Last note (round 3, `templates/follow_up_2.json`): DRAFT for approval, 13 Oct 2026

> Hi {{firstName}},
>
> One last note from me about Diablo Sugar Free for {{market}}. If sugar free confectionery is not
> a priority for you right now, just let me know and I will not follow up again. If it is, I would
> be glad to send samples and set up a short call with our Strategy Director.
>
> Best regards, then the Joshua signature block and the reminder's footer.
