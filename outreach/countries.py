"""Country names the "Add research to the queue" button accepts as the last part of a Location.

Standard library only (the outreachResearch skill can import it too). Matching ignores
capitals, accents, dots and "the". To accept a new name or short form, add it below.
"""

import difflib
import re
import unicodedata

COUNTRIES = """
Afghanistan; Albania; Algeria; Andorra; Angola; Antigua and Barbuda; Argentina; Armenia; Australia;
Austria; Azerbaijan; Bahamas; Bahrain; Bangladesh; Barbados; Belarus; Belgium; Belize; Benin; Bhutan;
Bolivia; Bosnia and Herzegovina; Botswana; Brazil; Brunei; Bulgaria; Burkina Faso; Burundi; Cabo Verde;
Cambodia; Cameroon; Canada; Central African Republic; Chad; Chile; China; Colombia; Comoros;
Republic of the Congo; Democratic Republic of the Congo; Costa Rica; Cote d'Ivoire; Croatia; Cuba; Cyprus;
Czech Republic; Denmark; Djibouti; Dominica; Dominican Republic; Ecuador; Egypt; El Salvador;
Equatorial Guinea; Eritrea; Estonia; Eswatini; Ethiopia; Fiji; Finland; France; Gabon; Gambia; Georgia;
Germany; Ghana; Greece; Grenada; Guatemala; Guinea; Guinea-Bissau; Guyana; Haiti; Honduras; Hungary;
Iceland; India; Indonesia; Iran; Iraq; Ireland; Israel; Italy; Jamaica; Japan; Jordan; Kazakhstan; Kenya;
Kiribati; Kosovo; Kuwait; Kyrgyzstan; Laos; Latvia; Lebanon; Lesotho; Liberia; Libya; Liechtenstein;
Lithuania; Luxembourg; Madagascar; Malawi; Malaysia; Maldives; Mali; Malta; Marshall Islands; Mauritania;
Mauritius; Mexico; Micronesia; Moldova; Monaco; Mongolia; Montenegro; Morocco; Mozambique; Myanmar;
Namibia; Nauru; Nepal; Netherlands; New Zealand; Nicaragua; Niger; Nigeria; North Korea; North Macedonia;
Norway; Oman; Pakistan; Palau; Palestine; Panama; Papua New Guinea; Paraguay; Peru; Philippines; Poland;
Portugal; Qatar; Romania; Russia; Rwanda; Saint Kitts and Nevis; Saint Lucia;
Saint Vincent and the Grenadines; Samoa; San Marino; Sao Tome and Principe; Saudi Arabia; Senegal; Serbia;
Seychelles; Sierra Leone; Singapore; Slovakia; Slovenia; Solomon Islands; Somalia; South Africa;
South Korea; South Sudan; Spain; Sri Lanka; Sudan; Suriname; Sweden; Switzerland; Syria; Taiwan;
Tajikistan; Tanzania; Thailand; Timor-Leste; Togo; Tonga; Trinidad and Tobago; Tunisia; Turkey;
Turkmenistan; Tuvalu; Uganda; Ukraine; United Arab Emirates; United Kingdom; United States; Uruguay;
Uzbekistan; Vanuatu; Vatican City; Venezuela; Vietnam; Yemen; Zambia; Zimbabwe;
Hong Kong; Macau; Puerto Rico; Greenland; Gibraltar; Isle of Man; Jersey; Guernsey; Faroe Islands;
Bermuda; Cayman Islands; Curacao; Aruba; Reunion; Guadeloupe; Martinique; French Guiana; New Caledonia;
French Polynesia; Guam; British Virgin Islands; Mayotte; Western Sahara
"""

# Other names and short forms people type, each pointing to a name above.
ALIASES = {
    "UK": "United Kingdom", "Great Britain": "United Kingdom", "Britain": "United Kingdom",
    "England": "United Kingdom", "Scotland": "United Kingdom", "Wales": "United Kingdom",
    "Northern Ireland": "United Kingdom", "GB": "United Kingdom",
    "US": "United States", "USA": "United States", "United States of America": "United States",
    "America": "United States",
    "UAE": "United Arab Emirates", "Emirates": "United Arab Emirates",
    "KSA": "Saudi Arabia", "Czechia": "Czech Republic", "Holland": "Netherlands",
    "Korea": "South Korea", "Republic of Korea": "South Korea", "Turkiye": "Turkey",
    "Ivory Coast": "Cote d'Ivoire", "Burma": "Myanmar", "Swaziland": "Eswatini",
    "Cape Verde": "Cabo Verde", "DRC": "Democratic Republic of the Congo", "DR Congo": "Democratic Republic of the Congo",
    "Congo": "Republic of the Congo", "East Timor": "Timor-Leste", "Macedonia": "North Macedonia",
    "Holy See": "Vatican City", "Russian Federation": "Russia", "Viet Nam": "Vietnam",
    "Lao PDR": "Laos", "Brunei Darussalam": "Brunei", "Kyrgyz Republic": "Kyrgyzstan",
    "Macao": "Macau", "Hong Kong SAR": "Hong Kong", "PRC": "China", "Mainland China": "China",
    "Eire": "Ireland", "Republic of Ireland": "Ireland",
}


def _key(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[.']", "", text.lower())
    text = re.sub(r"^the\s+", "", " ".join(text.replace("&", " and ").split()))
    return text


NAMES = [n.strip() for n in COUNTRIES.replace("\n", " ").split(";") if n.strip()]
_LOOKUP = {_key(n): n for n in NAMES}
_LOOKUP.update({_key(a): c for a, c in ALIASES.items()})
# How each accepted name is written: "u.s.a" -> "USA", "ireland" -> "Ireland".
_SPELLING = {_key(n): n for n in NAMES}
_SPELLING.update({_key(a): a for a in ALIASES})


def find(text):
    """The country a typed name means ("u.s.a" -> "United States"), or None if unknown."""
    return _LOOKUP.get(_key(text))


def spelling(text):
    """The usual way of writing a typed country name, keeping the name chosen:
    "u.s.a" -> "USA", "cote d'ivoire" -> "Cote d'Ivoire", "uk" -> "UK". None if unknown."""
    return _SPELLING.get(_key(text))


def suggest(text):
    """The closest known country names to a typo ("Infia" -> ["India"])."""
    matches = difflib.get_close_matches(_key(text), list(_LOOKUP), n=2, cutoff=0.75)
    out = []
    for m in matches:
        name = _LOOKUP[m]
        if name not in out:
            out.append(name)
    return out
