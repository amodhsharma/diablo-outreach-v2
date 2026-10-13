# Outreach email template

Status: **final, in use** (agreed by Ariel on 12 Oct 2026). One template for every Location and
Channel. The emails sent are built from `templates/first_email.json` and
`templates/follow_up.json`; this page shows them in plain words.

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

The team's version, used from 13 Oct 2026 (it replaced the 12 Oct "Potential Partnership" layout).

> Subject: Partnering to establish Diablo Sugar Free in the {{market_short}} sugar free snacks landscape
>
> Hi {{firstName}},
>
> I'm writing from the office of the Strategy Director at Diablo Sugar Free, where I look after
> international partners.
>
> {{personal_line}} We are a UK brand looking for the right partner in {{market_short}}.
>
> By way of introduction, we are the largest sugar free confectionery company in Europe. Chocolate
> bars and boxed chocolates, biscuits, wafers, sweets, spreads and jams, eleven categories in all.
> As you'll know, sugar free carries a better margin than standard confectionery, because the
> shopper accepts a higher price point. We supply more than 124 countries and are listed with
> Carrefour, Lidl, Tesco and Holland & Barrett.
>
> You can see our catalogue here: {{catalogue_link}}
>
> I'd love to set up a call between myself, your team and our Strategy Director, so we can look at
> what the range would need to earn properly for your customers.
>
> Would this week work, or would next week be better suited? (+ booking link sentence once set)
>
> Best regards, then the Joshua signature block

The personal line is written per company by Claude and starts "I thought I'd reach out as we
noticed...", for example: "I thought I'd reach out as we noticed Makro already runs a
dieet-voeding category alongside its grocery range."

## Reminder (3 days later, same thread, only if nobody at the company has replied)

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
