# Write a personal line for each contact

You write for Diablo Sugar Free, Europe's largest no added sugar and sugar free snacks company:
117+ products across chocolate, biscuits, wafers, sweets, cakes, spreads, syrups and protein bars,
sweetened with stevia and inulin, never aspartame.

Each contact below works at a company our research found. They will get a cold email (agreed
14 Oct 2026) that reads:

> Hi <first name>,
>
> I'm writing from the office of the Strategy Director at Diablo Sugar Free, where I look after
> international partners.
>
> By way of introduction, we are the largest sugar-free confectionery company in Europe. ... We
> supply more than 126 countries and are listed with Carrefour, Lidl, Tesco and Holland & Barrett.
>
> **<your personal line, its own paragraph>**
>
> Attaching a catalogue for your reference: <link>
>
> We would be more than glad to set up a call between your team and our outreach or strategy team
> leads, ...

You write only the personal line. Everything else, the subject line included, is fixed.

Write lines for all {{count}} contacts.

## The tone (agreed 14 Oct 2026)

We are pitching our products to them, and they have the upper hand. Write with respect: look up to
them and recognise what they have built. They are not our friends, so be formal, never casual.
Propose the idea and leave the decision with them. Never impose, and never assume what they or
their customers have or have not already thought of.

## The four styles

Each contact has been given a **style** (A, B, C or D, in its `style` field), picked at random.
Write that contact's line in exactly that style. Each style is a fixed shape: fill the parts in
[brackets] from that company's research and keep every other word as it is.

**A. Respect for their reach**
"We have great respect for the way your team [what they do and for whom]. With such established
reach [across their channels], we would be honoured if you would consider whether a sugar free
range could have a place in your portfolio."

**B. Their track record**
"Your team's work in [a specific achievement from the research] speaks for itself. We would value
the opportunity to present our sugar free range and to hear whether you feel it could sit
alongside [the brands you already represent / the products you already offer]."
(End with "the brands you already represent." for distributors, wholesalers and importers, and
"the products you already offer." for retailers and online sellers.)

**C. Their range**
"Your range, [from X to Y], reflects a careful choice of [brands or products] for [their market].
We would welcome the chance to present our sugar free range for your consideration, should you see
a place for it."

**D. Partnership**
"We hold your team in high regard for [a specific achievement or position from the research]. We
would be grateful for the opportunity to discuss whether our sugar free range could be a worthwhile
addition to your business."

## Filling the [brackets]

Only the facts in each contact's `company` block: name, location, channel, where it is based,
what it distributes or sells, the channels it supplies, the sugar free brands it carries, what it
does well and why it fits Diablo. Plus the person's job title and seniority.

- Every company is different: use what that company's research says, in your own words, and keep
  it short. Never copy another company's details.
- Do **not** search the web and do not add any fact that is not in the block.
- Use `what_they_do_well` first. If it is empty, use the most specific true fact you have (what
  they distribute, who they supply).
- If the block holds too little for the [brackets], keep them plain and true (for example "the
  way your team serves the trade in Zurich"). Never fill a gap with a guess.
- Fit the wording to the person's role where the shape allows it.

## Rules

- "We", never "I", "me" or "my": the line pitches Diablo on behalf of the whole team.
- Two sentences, 60 words or fewer. No greeting and no first name (the email already has them).
- Use the company name at most once; "your team" is usually better.
- Do not mention Diablo's partners in their market, its countries or its UK base.

## Never

- Invented facts, numbers, names or brands.
- Casual words: fun, enjoy, enjoyed, lovely, love, chat, exciting.
- Over-the-top praise: incredible, amazing, outstanding, wonderful, fantastic, world-class.
- Guesses about what they lack or have not considered ("you don't have", "missing", "a gap",
  "your customers have started asking").
- Health claims, or the words "diabetic", "diabetes" or "healthy".
- Exclamation marks, emojis, links, email addresses, phone numbers or {{placeholders}}.
- Pushy sales talk ("act now", "limited time", "special offer", "guarantee").

## Writing

British English (flavour, specialise, organise). No em dashes or en dashes: use a comma or a full
stop. No Oxford commas ("biscuits, wafers and sweets", never "biscuits, wafers, and sweets").
Write "sugar free" without a hyphen.

## Examples (made-up companies, to show the shape only)

- Style A, a distributor: "We have great respect for the way your team takes Scandinavian snack
  brands into independent pharmacies across Ireland. With such established reach across pharmacy
  and convenience, we would be honoured if you would consider whether a sugar free range could have
  a place in your portfolio."
- Style B, a retailer: "Your team's work in building a free from aisle across forty stores speaks
  for itself. We would value the opportunity to present our sugar free range and to hear whether
  you feel it could sit alongside the products you already offer."
- Style C, a wholesaler: "Your range, from Belgian chocolate to Dutch biscuits, reflects a careful
  choice of brands for the Benelux trade. We would welcome the chance to present our sugar free
  range for your consideration, should you see a place for it."
- Style D, an importer: "We hold your team in high regard for introducing three European
  confectionery brands to Polish retail. We would be grateful for the opportunity to discuss
  whether our sugar free range could be a worthwhile addition to your business."

## Save your answer

Save `work_mail/draft.json` in exactly this shape, one entry per contact, using each contact's
`contact_id` exactly as given (the style is added for you):

```json
{
  "lines": [
    {"contact_id": "123", "personal_line": "..."}
  ]
}
```

## The contacts

```json
{{contacts_json}}
```
