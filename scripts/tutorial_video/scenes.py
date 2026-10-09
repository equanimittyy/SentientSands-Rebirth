"""The tutorial videos: the browser steps of each video and the bubble note of each step.

Each scene id names the dropdown of the Tutorial tab that shows the video. A target is a function of the page, because
the web app builds its pages after load. The notes follow the tutorial text: one short sentence in Simplified Technical
English, from the view of the player.
"""
import re
from dataclasses import dataclass, field
from typing import Callable

ZOOM = 1.5


@dataclass
class Step:
    action: str
    target: Callable | None = None
    note: str | None = None
    value: str | None = None
    zoom: float = ZOOM


@dataclass
class Scene:
    id: str
    title: str
    steps: list = field(default_factory=list)
    outro: str | None = None


def goto(tab):
    return Step("goto", value=tab)


def look(target, note, zoom=ZOOM):
    return Step("look", target, note, zoom=zoom)


def click(target, note=None, zoom=ZOOM):
    return Step("click", target, note, zoom=zoom)


def fill(target, text, note=None, zoom=ZOOM):
    return Step("fill", target, note, text, zoom)


def append(target, text, note=None, zoom=ZOOM):
    return Step("append", target, note, text, zoom)


def choose(target, option, note=None, zoom=ZOOM):
    """option is a part of the text of the option, so a label such as "Limited (default)" needs no exact match."""
    return Step("choose", target, note, option, zoom)


def summary(page, name):
    """The summary of the card whose name is exactly name, so the card ollama does not match its profile ollama-llama3."""
    return page.locator("details.card > summary").filter(has=page.get_by_text(name, exact=True)).first


def card(page, name):
    return summary(page, name).locator("..")


def legend(page, text):
    return page.locator("legend", has_text=text).first


def default_profile(page):
    return page.locator("fieldset", has=page.locator("legend", has_text="Default LLM Profile")).locator("select").first


def task_card(page, task):
    return page.locator(".card").filter(has=page.locator(".card-head strong", has_text=re.compile(f"^{task}$"))).first


def add_button(scope, page, placeholder):
    return scope.locator("form", has=page.get_by_placeholder(placeholder)).get_by_role("button", name="Add")


def record(page, name):
    return page.locator("#record-list button.record").filter(has=page.get_by_text(name, exact=True)).first


SCENES = [
    Scene("connect-model", "Connect a model", [
        goto("#llm"),
        look(lambda p: legend(p, "Providers"), "A provider is one AI service, such as OpenRouter.", 1.2),
        click(lambda p: summary(p, "openrouter"), "Open the card of your service."),
        fill(lambda p: card(p, "openrouter").get_by_label("API key"), "sk-or-v1-0123456789abcdef", "Paste your API key."),
        click(lambda p: summary(p, "gemini-3-flash"), "Open a profile. A profile is one model."),
        click(lambda p: card(p, "gemini-3-flash").get_by_role("button", name="List models"), "List models gets the model IDs from the service."),
        look(lambda p: card(p, "gemini-3-flash").get_by_label("Model ID"), "Type in Model ID to find a model."),
        click(lambda p: p.get_by_role("button", name="Test gemini-3-flash"), "Press Test."),
        look(lambda p: card(p, "gemini-3-flash").locator(".card-actions"), "OK means that the model replies."),
        choose(default_profile, "gemini-3-flash", "Choose the profile as the Default LLM Profile."),
        click(lambda p: p.locator("#llm-save"), "Press Save."),
    ], "Your NPCs now talk with this model."),
    Scene("campaigns", "Campaigns", [
        goto("#campaigns"),
        look(lambda p: p.locator("fieldset", has=legend(p, "Current Campaign")).locator("select"), "The game plays the current campaign."),
        fill(lambda p: p.get_by_label("Campaign Name"), "Second Run", "To start a new playthrough, name a new campaign."),
        look(lambda p: p.locator("#campaigns form.add select"), "It starts as a copy of a world template."),
        click(lambda p: p.get_by_role("button", name="Create"), "Press Create."),
        choose(lambda p: p.locator("fieldset", has=legend(p, "Current Campaign")).locator("select"), "Second Run", "Choose the campaign to switch to it."),
        look(lambda p: p.get_by_role("button", name="Cull future data"), "Loaded an older save? Cull makes NPCs forget what came after it."),
    ]),
    Scene("tasks", "Tasks and fallbacks", [
        goto("#llm"),
        look(lambda p: legend(p, "Tasks"), "Each task is one kind of AI call.", 1.2),
        choose(lambda p: p.get_by_label("Add a profile to Chat", exact=True), "deepseek-v3.2", "Add a fallback profile to a task."),
        click(lambda p: task_card(p, "Chat").get_by_role("button", name="Move deepseek-v3.2 up"), "Move a profile up to try it first."),
        look(lambda p: task_card(p, "Chat").get_by_label("Deadline (s)"), "Keep the deadline under 60 s. The game waits only that long."),
        click(lambda p: p.locator("#llm-save"), "Press Save."),
    ]),
    Scene("local-models", "Local models", [
        goto("#llm"),
        fill(lambda p: p.get_by_placeholder("New provider name"), "llamacpp", "For llama.cpp, add a provider."),
        look(lambda p: p.get_by_label("Provider type"), "Keep the type OpenAI-compatible."),
        click(lambda p: add_button(p, p, "New provider name"), "Press Add."),
        fill(lambda p: card(p, "llamacpp").get_by_label("Base URL"), "http://localhost:8080/v1", "Type the address of llama.cpp, with /v1 at the end."),
        look(lambda p: card(p, "llamacpp").get_by_label("API key"), "A local server needs no API key."),
        fill(lambda p: card(p, "llamacpp").get_by_placeholder("New profile name"), "llamacpp-local", "Add a profile for the model."),
        click(lambda p: add_button(card(p, "llamacpp"), p, "New profile name"), "Press Add."),
        click(lambda p: card(p, "llamacpp-local").get_by_role("button", name="List models"), "List models shows the model that llama.cpp runs."),
        fill(lambda p: card(p, "llamacpp-local").get_by_label("Model ID"), "gemma-3-4b-it-Q4_K_M.gguf"),
        click(lambda p: p.get_by_role("button", name="Test llamacpp-local"), "Press Test."),
        choose(default_profile, "llamacpp-local", "Choose the profile as the Default LLM Profile."),
        click(lambda p: p.locator("#llm-save"), "Press Save."),
    ]),
    Scene("memories", "How NPCs remember", [
        goto("#editor"),
        click(lambda p: p.get_by_role("tab", name="Dialogue & Memories"), "Dialogue & Memories lists your conversations."),
        click(lambda p: p.locator("#thread-list button.record").nth(1), "Choose a conversation.", 1.2),
        look(lambda p: p.get_by_label("Memorised Summary").first, "The NPCs remember this summary."),
        append(lambda p: p.get_by_label("Memorised Summary").first, " They agreed to meet again.", "Edit it to change what they remember."),
        click(lambda p: p.locator("#editor-save"), "Press Save."),
    ]),
    Scene("rumors", "Rumors and events", [
        goto("#editor"),
        click(lambda p: p.get_by_role("tab", name="Events", exact=True), "Events lists the kills, the captures, and their rumors."),
        fill(lambda p: p.get_by_placeholder("Add a custom rumour"), "A stranger paid for a round of drinks for the whole bar.", "Type a rumor of your own."),
        click(lambda p: add_button(p, p, "Add a custom rumour"), "Press Add. NPCs can now mention it."),
        look(lambda p: p.get_by_role("button", name="Generate Rumor").first, "Generate Rumor writes the rumor of an event now."),
    ]),
    Scene("profiles", "NPC profiles and bios", [
        goto("#editor"),
        choose(lambda p: p.get_by_label("Show only").first, "Characters", "Show only the characters."),
        click(lambda p: record(p, "Jorge"), "Choose a character."),
        look(lambda p: p.locator("#record-form").get_by_label("Personality").first, "The personality, backstory, and speech make the NPC."),
        click(lambda p: p.get_by_role("button", name="Generate Bio"), "Generate Bio writes the bio now."),
        fill(lambda p: p.locator("#bio textarea"), "A former slave who distrusts every noble.", "Instructions are optional."),
        look(lambda p: p.locator("#bio button[value=ok]"), "Press Write. Then check the text and press Save."),
        click(lambda p: p.locator("#bio button[value=cancel]")),
    ]),
    Scene("canon", "World canon", [
        goto("#editor"),
        look(lambda p: p.get_by_role("switch", name="Show seeded data"), "Seeded entries come from the template of the campaign."),
        choose(lambda p: p.get_by_label("Show only").first, "Locations", "Show only one kind of entry."),
        click(lambda p: record(p, "The Hub"), "Choose an entry."),
        choose(lambda p: p.get_by_label("Knowledge Level"), "Secret", "Knowledge Level sets which NPCs know the entry."),
        look(lambda p: p.get_by_role("button", name="Add knower"), "Only the names that you add to Known by know the secret."),
        click(lambda p: p.locator("#editor .discard"), "Discard drops your changes."),
    ]),
    Scene("templates", "World templates", [
        goto("#editor"),
        click(lambda p: p.get_by_role("tab", name="Templates"), "Templates are the seeds of new campaigns."),
        look(lambda p: p.get_by_label("World template"), "SSR Vanilla is read-only."),
        fill(lambda p: p.get_by_label("Name of the copy"), "My World", "Name a copy."),
        click(lambda p: p.get_by_role("button", name="Duplicate"), "Press Duplicate. You can edit the copy."),
        look(lambda p: p.get_by_role("button", name="Export"), "Export saves the template as a file that you can share."),
    ]),
    Scene("prompts", "Prompts", [
        goto("#prompts"),
        click(lambda p: summary(p, "Reply rules"), "Open a prompt."),
        append(lambda p: p.get_by_label("Reply rules", exact=True), "\nKeep each reply under three sentences.", "Edit the text."),
        click(lambda p: p.locator("#prompts-save"), "Press Save."),
        look(lambda p: card(p, "Reply rules").locator(".badge", has_text="Edited"), "Edited marks your change."),
        look(lambda p: card(p, "Reply rules").get_by_role("button", name="Use default"), "Use default puts back the text that SSR ships."),
    ]),
    Scene("test-search", "Logs and tests", [
        goto("#settings"),
        choose(lambda p: p.locator("select[name=log_level]"), "DEBUG", "Set Log level to DEBUG."),
        click(lambda p: p.locator("#settings-form .save"), "Press Save."),
        goto("#editor"),
        click(lambda p: p.locator("details.debug-only > summary"), "Test search shows what an NPC gets with a line."),
        fill(lambda p: p.get_by_label("Line to search"), "Have you heard about the Phoenix?", "Type a line."),
        choose(lambda p: p.get_by_label("Character to talk to"), "Jorge", "Choose the NPC who hears it."),
        click(lambda p: p.locator("details.debug-only").get_by_role("button", name="Search")),
        look(lambda p: p.locator("#test-search-result"), "These entries, memories, and rumors reach the NPC.", 1.0),
    ]),
]
