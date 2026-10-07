"""The bounties that SSR puts on NPCs through the bounty system of the game."""

# The order of CrimeEnum in KenshiLib after CRIME_NONE, so the plugin takes CRIMES[i] as the enum value i + 1
CRIMES = (
    "ENSLAVING", "LOCKPICKING", "STEALING", "MURDER", "ASSAULT", "ASSAULT_VIP", "SLAVE_FREEING", "SMUGGLING",
    "TERRORISM", "LOOTING", "TRESPASSING", "ESCAPE_PRISON", "FENCING", "FARM_EATING", "KIDNAPPING", "UNIFORM_THEFT",
)
# The Holy Nation, the United Cities, and the Shek Kingdom by game ID: the law of each of them sets every bounty at one price
ISSUERS = ("1083-gamedata.base", "defaultEmpireFactionSID", "11624-Dialogue (10).mod")
# The bandit factions that attack people in general, from the Kenshi wiki and the default relations of the game data. Rival
# gangs that fight only certain factions, such as the Reavers and the Red Sabres, stay out.
TARGETS = {
    "16860-gamedata.base": "Bloodraiders",
    "2758392-Bandits Expansion.mod": "Desolate Plunderers",
    "200-gamedata.base": "Dust Bandits",
    "96175-rebirth.mod": "Grass Pirates",
    "2757329-Hill Bandits.mod": "Hill Marauders",
    "54297-rebirth.mod": "Rebel Farmers",
    "1085-gamedata.base": "Sand Ninjas",
    "95512-rebirth.mod": "Scavengers",
    "42235-rebirth.mod": "Shrieking Bandits",
    "63028-Dialogue.mod": "Skin Bandits",
    "1305-gamedata.base": "Starving Bandits",
    "2757403-Swamp Bandits.mod": "Swamp Ruffians",
    "1533849-Northern Bandits Expanded.mod": "The Bastards",
    "1533851-Northern Bandits Expanded.mod": "The Deluged",
    "96261-rebirth.mod": "The Gorrillo Bandits",
    "1532482-__May 18 2.mod": "Yabuta Outlaws",
}
