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
| Signature | Joshua, Initial Outreach Team, then "Diablo Sugar Free" linked to the website and "(B Healthy Ltd, London)" (agreed 14 Oct 2026; no phone, no separate website line). Shown after "Best regards," as an indented block with a thin grey bar on the left, like a quote. Templates 2, forward and reminder |
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

## Forward to the next person (persons 2 to 4; agreed 14 Oct 2026, `templates/forward.json`)

Sent by button 3 from the same mailbox as a forward of the latest email in the company's chain, so
the earlier email appears underneath. Subject: "Fwd: " and the introduction's subject.

> Hi {{firstName}},
>
> In case our earlier note to your colleague [full name] did not reach the right desk, we wanted to
> share it with you as well.
>
> {{personal_line}}
>
> Would a brief 10-minute call with our outreach lead work for you at a time of your convenience?
>
> Best regards, then the Joshua signature and the first email's footer.

The colleague is the person at the same company emailed most recently who has not replied, never
a bounced person. The name is filled in only when the email is sent; it is never stored in GitHub.

## Reminder to person 1 (the last email; agreed 14 Oct 2026, `templates/follow_up.json`)

Sent once, as a reply in person 1's own thread, after the loop and at least a week after their
introduction. Persons 2 to 4 never get a reminder.

> Hi {{firstName}},
>
> We wrote to you about a week ago about bringing Diablo Sugar Free to {{market}}, and we
> appreciate how busy things can be. We would still value the chance to share our range with your
> team.
>
> Would a brief 10-minute call with our outreach lead work for you at a time of your convenience?
>
> Best regards, then the Joshua signature and the reminder footer.

3 days after the reminder with no reply from anyone, the company becomes Unqualified.

## Footer (every email)

Grey (#888888), slightly smaller text (12px), under a thin full-width grey line (agreed 12 Oct 2026;
the company line moved into the signature on 14 Oct 2026):

> ---
> We found your business details in public and commercial sources. If you would rather not hear
> from us, reply "no thanks" and we will not contact you again.
>
> Privacy notice: [https://www.diablosugarfree.com/policies/privacy-policy](https://www.diablosugarfree.com/policies/privacy-policy)

The privacy notice link is clickable. The reminder's
footer leaves out the "We found your business details..." sentence.

## Booking link

- The booking link (`send.booking_link`) is the Calendly page
  https://calendly.com/amodh-diablosugarfree/introductory-call-with-diablo-sugar-free (set on
  14 Oct 2026). Template 2 shows it on its own line after "you can do it from the link below".

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
> Attaching a catalogue [here]({{catalogue_link}}) for your reference.
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
> Joshua
> Initial Outreach Team
> [Diablo Sugar Free](https://www.diablosugarfree.com) (B Healthy Ltd, London)
>
> (grey footer: the opt-out sentence and the privacy notice)

Changed on 14 Oct 2026: the introduction now comes before the personal line; the sentence "We are
a UK brand and do not yet have a direct partner in ..." was removed; the catalogue, call and
booking sentences were reworded as above. The 126 countries figure stays as it is. Later the same
day: "here" in the catalogue sentence became the link to https://www.diablosugarfree.com/pages/catalogue-2026
(final), the signature gained the linked company name, and the phone and website lines and the
footer's company line were removed.

Which file is used is set in `config/settings.yaml` under `send.templates`. To go back to
`templates/template_1.json`, change that path; nothing else needs to change.

## Template 3: the introduction to person 1 (in use from 15 Oct 2026)

Ariel's new introduction, in `templates/template_3.json`. Template 2 is kept unchanged; to go back,
set `send.templates.first_email` to `templates/template_2.json` in `config/settings.yaml`.

**Subject:** A sugar-free brand with no {{country_name}} partner yet

> Hi {{firstName}},
>
> I'm writing from the office of the Strategy Director at Diablo Sugar Free, where I look after
> international partners.
>
> I thought I'd reach out as we noticed {{companyName}} {{company_note}}. We are a UK brand without
> a direct partner in {{market_country}} yet.
>
> By way of introduction, **we are Europe's largest sugar-free confectionery company**, with 117
> products across 11 categories, from cakes and biscuits to wafers and spreads.
>
> As you'll know, sugar-free carries a better margin than standard confectionery, as the shopper
> accepts a higher price point. **We supply more than 126 countries and are listed with Carrefour,
> Tesco, Lidl and Holland & Barrett.**
>
> Here is the link to our catalogue for your information: [diablosugarfree.com/pages/catalogue-2026](https://www.diablosugarfree.com/pages/catalogue-2026)
>
> I'd love to set up a call with your team and our Strategy Director to look at what the range
> would need to earn properly for your professional customers.
>
> Would this week work, or would next week be better suited?
>
> Best regards,
>
> Joshua
> International Account Executive
> Diablo Sugar Free
> Book a quick meeting with us: [calendly.com/outreach-diablo/intro](https://calendly.com/outreach-diablo/intro)
>
> ---
> <small>We found your business details in public and commercial sources. If you would rather not
> hear from us, reply "no thanks" and we will not contact you again.</small>

- {{company_note}} is the new contact field **Outreach company note**, written by the
  outreach-mail-writing skill from the research (healthy eating first, otherwise the closest true
  fact) and checked by you at gate 2.
- {{country_name}} is the country of the Location; {{market_country}} adds "the" where English
  needs it ("the Netherlands").
- No privacy link (agreed 15 Oct 2026: as few links as possible).
- The forward and reminder keep their current wording and signature until Ariel sends new ones.


## Person 1's reminder: follow_up_2.json (in use from 15 Oct 2026)

Ariel's "Bad Jokes" email, fixed text (nothing in it is written by Claude). Sent once to person 1,
at least 7 days after their introduction and 3 days after the last email at the company, as a
reply to their own first email but with its own subject, so it arrives as a separate email. No
colleague is named. `follow_up.json` is kept unchanged; to go back, set `send.templates.reminder`
to `templates/follow_up.json`.

**Subject:** Bad Jokes + Europe's largest Brand

> Hi {{firstName}},
>
> I imagine your inbox is about as full as a regular chocolate bar is of sugar. Sadly, we can only
> fix one of those.
>
> I hope that bad joke buys me another email :)
>
> Bad jokes aside, as mentioned, we are Diablo Sugar Free, Europe's largest sugar-free
> confectionery company, with 117 snacks across 11 categories, from cakes and biscuits to wafers
> and spreads, all sweetened without aspartame. Our catalogue: [diablosugarfree.com/pages/catalogue-2026](https://www.diablosugarfree.com/pages/catalogue-2026)
>
> We supply more than 126 countries and are listed with Carrefour, Tesco, Lidl and Holland &
> Barrett, etc, but do not yet have a direct partner in {{market_country}}.
>
> I'd love to set up a call with your team and our Strategy Director to look at what the range
> would need to earn properly for your professional customers.
>
> Would this week work, or would next week suit better?
>
> Best regards,
>
> Joshua
> International Account Executive
> Diablo Sugar Free
> Book a quick meeting with us: [calendly.com/outreach-diablo/intro](https://calendly.com/outreach-diablo/intro)
>
> ---
> <small>We found your business details in public and commercial sources. If you would rather not
> hear from us, reply "no thanks" and we will not contact you again.</small>

## Forward to persons 2 to 4: forward_2.json (in use from 19 Oct 2026)

Replaces `templates/forward.json` (kept unchanged, no longer used). Sent from the same mailbox as
the first email, with the earlier email of the chain underneath. The reason given is the company's
Outreach company note, the same fact person 1 saw; the personal line is not used. The forward goes
out only when that person's Outreach company note is filled in.

Subject: Fwd: <the first email's subject>

> Hi {{firstName}},
>
> A few days ago I wrote to your colleague {{colleague_name}}, as we noticed {{companyName}} {{company_note}}. We do not yet have a direct partner in {{market_country}}, and we believe your company would be the right fit for us.
>
> My earlier note is below, and our catalogue is here: <short catalogue link>
>
> Would this week work for a short call with our Strategy Director, or would next week suit better?
>
> Best regards,
>
> {{sender_name}}
> International Account Executive
> Diablo Sugar Free
> Book a quick meeting with us: <short booking link>
>
> Footer: the full-width line and the "no thanks" sentence in small grey text (no privacy link).

## Company inboxes: template_no_info_apollo_1.json and follow_up_no_info_apollo_1.json (in use from 19 Oct 2026)

Used only when Apollo holds nobody at a company and the company's own website shows a contact
address (purchasing first, then sales, then info@ and similar). That address is one contact with
the job title "Company inbox (from website)". Its first email goes through its own campaign each
month ("Diablo | <MONTH> | Company inboxes", at most 5 a day per sending mailbox); its reminder
goes at least 7 days later from the same mailbox; then the company is Unqualified. There are no
forwards.

First email: template 3 word for word, except:

> Hello {{companyName}} team,
>
> I'm writing from the office of the Strategy Director at Diablo Sugar Free, where I look after international partners. Could you kindly pass this on to the person responsible for purchasing or new brands?

Reminder: follow_up_2 ("Bad Jokes + Europe's largest Brand") word for word, except the greeting
"Hello {{companyName}} team," and, before "I'd love to set up a call...":

> If this is better suited to a colleague, could you kindly pass it on to the person responsible for purchasing or new brands?
