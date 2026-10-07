"""The bounties that SSR puts on NPCs through the bounty system of the game."""

from chat.retrieval import name_words

# The order of CrimeEnum in KenshiLib after CRIME_NONE, so the plugin takes CRIMES[i] as the enum value i + 1
CRIMES = (
    "ENSLAVING", "LOCKPICKING", "STEALING", "MURDER", "ASSAULT", "ASSAULT_VIP", "SLAVE_FREEING", "SMUGGLING",
    "TERRORISM", "LOOTING", "TRESPASSING", "ESCAPE_PRISON", "FENCING", "FARM_EATING", "KIDNAPPING", "UNIFORM_THEFT",
)
# The Holy Nation, the United Cities, and the Shek Kingdom by game ID
ISSUERS = ("1083-gamedata.base", "defaultEmpireFactionSID", "11624-Dialogue (10).mod")


def issuer_ids(target, factions):
    """The ISSUERS that the campaign sets against target, the faction of the target: each one in its enemies, and each one
    that lists it in theirs. Each of them sets the bounty at the same price. The names match by name words, so "Holy
    Nation" names The Holy Nation."""
    def names(faction):
        return {name_words(name) for name in (faction["name"], *faction["aliases"])}

    def enemies(faction):
        return {name_words(name) for name in faction["fields"].get("enemies", [])}

    own = names(target)
    return [
        faction["faction_id"] for faction in factions
        if faction["faction_id"] in ISSUERS and faction["faction_id"] != target["faction_id"] and (names(faction) & enemies(target) or own & enemies(faction))
    ]
