# Channels research no longer searches (paused 10 Nov 2026)

On 10 Nov 2026 Ariel decided that research looks only for big wholesalers, distributors, importers
and supermarket chains (prompt version 6). The channels below were switched off that day. Ariel may
ask to bring some back one day, so this file keeps everything needed to do it. Nothing here runs.

## The paused channels

| Channel (as typed in button 2) | Who they are | Why it fit Diablo | Searched in | Rule sheet it used (version 5) |
|---|---|---|---|---|
| retailers (independent grocers, convenience store chains) | Shops and small chains that buy direct and sell to shoppers | Whole range | Country and cities | retailer_5 |
| pharmacy and drugstore chains | Pharmacy and drugstore chains with a food or snack shelf | Sugar free and no added sugar range | Country | retailer_5 |
| health food and organic retailers | Health food, organic and free-from shops and chains | Sugar free, gluten free and vegan products | Country | retailer_5 |
| online sellers | Companies that buy stock and resell it on Amazon and other marketplaces | Whole range | Country | marketplace_seller_5 |
| petrol station and convenience chains | Forecourt shops and convenience chains | Impulse-size products | Country | petrol_convenience_5 |
| travel retail | Airport shops, duty free, railway station shops, airline and train trolleys | Single-serve packs and gift boxes | Country | retailer_5 |
| sports shops and sports nutrition shops | Sports shops (also sports equipment shops with healthy food), sports nutrition and fitness shops | Muesli bars, sugar free snacks | Country and cities | retailer_5 |
| diabetic, low sugar and keto shops | Shops and websites for people managing sugar, low carb and keto | Every product is sugar free or no added sugar (no health claims) | Country | retailer_5 |
| gluten free and free from shops | Coeliac shops, free-from distributors and allergy-friendly online stores | 35 gluten free products; many free from egg, peanuts, dairy or nuts | Country | retailer_5 |
| vegan and vegetarian shops | Vegan and vegetarian shops and distributors | 13 vegan, 88 vegetarian, 87 gelatin free | Country | retailer_5 |
| kosher shops | Kosher supermarkets and grocers | 56 kosher products | Country | kosher_shop_5 |
| corporate gifting and hamper companies | Gift boxes and hampers for companies, Christmas and events | Advent calendar, chocolate boxes and gift boxes | Country and cities | general_5 |
| office snack and pantry suppliers | Deliver snacks to offices and stock workplace pantries | Single-serve bars, muffins and cookies | Country and cities | general_5 |
| snack vending operators | Install snack machines and choose what goes in them (not coffee-led) | Single-serve packs | Country and cities | general_5 |
| hospital and care home shops | Shops and kiosks in hospitals and care homes that sell packs as they are | Single-serve packs | Country | hospital_shop_5 |
| seasonal and gift shops | Christmas, gift and souvenir shops | Advent calendar, chocolate boxes, gift boxes | Country and cities | retailer_5 |
| leisure and venue snack suppliers | Cinemas, leisure parks, pools, stadiums and ski resort shops | Single-serve packs | Country | general_5 |
| hotel minibar suppliers | Stock hotel minibars and in-room treats | Chocolate bars, buttons, sweets | Country | general_5 |
| snack subscription boxes | Monthly snack or diet boxes posted to shoppers | Whole range | Country | general_5 |
| promotional merchandise companies | Giveaways and co-branded sweets for events | Chocolate and sweets | Country | general_5 |

The narrower searches they had (config/coverage.json before 10 Nov 2026):
- retailers: retailers, supermarket chains, independent grocers, convenience store chains
- online sellers: online sellers, online sweets shops, online grocery shops, marketplace sellers
- pharmacy and drugstore chains: pharmacy chains, drugstore chains
- health food and organic retailers: health food shops, organic shops
- wholesalers also had "kiosk wholesalers" (now covered by "kiosk and convenience wholesalers")

Each of these channels' first email still works: the bond lines in `config/bond_channels.json` (sports
shops, pharmacy chains, office snacks, petrol stations, vending, gifting, hospital shops, hotel
minibars, leisure venues, travel retail, promotional merchandise) were left in place, and the mail
writing skill still knows them.

## How to bring one back

1. Add the channel name to `country_channels` in `config/coverage.json` (and to `city_channels` if it
   was searched in the cities), with its narrower searches if it had any.
2. Give it rules that fit small businesses. Prompt version 6 is for big partners only (its HARD RULE 12
   rejects small companies), so a shop channel searched under version 6 would find almost nothing. Two
   ways:
   - research it on its own under version 5 (set `prompt_version: 5` in
     `skills/outreachResearch/settings.yaml` for that run, then back to 6): the version 5 files
     (`prompts/channel_prompt_5.md` and `prompts/channels/*_5.md`) are kept unchanged;
   - or write a version 6 rule sheet for it that lifts the size rule for that channel only.
3. Update `docs/channels.json` and this file, and the README and handbook.
