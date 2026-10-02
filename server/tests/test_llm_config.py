import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import llm_config

PROVIDERS = {
    "openrouter": {"api_key": "sk-or-secret-1234", "base_url": "https://openrouter.ai/api/v1"},
    "player2": {"api_key": "sk-player2-local", "base_url": "http://127.0.0.1:4315/v1", "game_key": "game"},
}
MODELS = {
    "kimi": {"provider": "openrouter", "model": "moonshotai/kimi-k2.5"},
    "player2-default": {"provider": "player2", "model": "default"},
    "orphan": {"provider": "missing", "model": "x"},
}


def built():
    return llm_config.build(PROVIDERS, MODELS, "kimi")


class BuildTest(unittest.TestCase):
    def test_routes_every_task_to_the_default_profile(self):
        config = built()
        self.assertEqual(config["default_profile"], "kimi")
        self.assertEqual(set(config["routes"]), set(llm_config.TASKS))
        for route in config["routes"].values():
            self.assertEqual(route["profiles"], [llm_config.DEFAULT_SLOT])
            self.assertEqual(llm_config.route_profiles(config, route), ["kimi"])
            self.assertEqual(route["deadline"], llm_config.DEFAULT_DEADLINE)
        self.assertEqual(config["routes"]["profile"]["max_tokens"], 1500)

    def test_keeps_keys_and_sets_provider_type_from_name(self):
        config = built()
        self.assertEqual(config["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")
        self.assertEqual(config["providers"]["openrouter"]["type"], "openai")
        self.assertEqual(config["providers"]["player2"]["type"], "player2")
        self.assertEqual(config["providers"]["player2"]["game_key"], "game")

    def test_skips_models_whose_provider_is_missing(self):
        self.assertNotIn("orphan", built()["profiles"])

    def test_falls_back_to_the_first_model_for_an_unknown_first_profile(self):
        config = llm_config.build(PROVIDERS, MODELS, "gone")
        self.assertEqual(config["default_profile"], "kimi")

    def test_built_config_is_valid(self):
        self.assertEqual(llm_config.validate(built()), [])


class ValidateTest(unittest.TestCase):
    def test_rejects_profile_with_missing_provider(self):
        config = built()
        config["profiles"]["kimi"]["provider"] = "gone"
        errors = llm_config.validate(config)
        self.assertTrue(any("gone" in error["message"] for error in errors))
        self.assertEqual([error["field"] for error in errors], [["profiles", "kimi", "provider"]])

    def test_rejects_route_with_missing_profile(self):
        config = built()
        config["routes"]["chat"]["profiles"] = [llm_config.DEFAULT_SLOT, "gone"]
        errors = llm_config.validate(config)
        self.assertTrue(any("gone" in error["message"] for error in errors))
        self.assertEqual([error["field"] for error in errors], [["routes", "chat", "profiles", 1]])

    def test_route_needs_the_default_slot_once(self):
        config = built()
        config["routes"]["chat"]["profiles"] = ["kimi"]
        config["routes"]["ambient"]["profiles"] = [llm_config.DEFAULT_SLOT, llm_config.DEFAULT_SLOT]
        fields = [error["field"] for error in llm_config.validate(config)]
        self.assertEqual(fields, [["routes", "chat", "profiles"], ["routes", "ambient", "profiles"]])

    def test_rejects_missing_or_malformed_default_profile(self):
        for default in ("gone", None, ["kimi"]):
            config = built()
            config["default_profile"] = default
            self.assertEqual([error["field"] for error in llm_config.validate(config)], [["default_profile"]])

    def test_rejects_missing_task_and_bad_numbers(self):
        config = built()
        del config["routes"]["ambient"]
        config["routes"]["chat"]["temperature"] = 3
        config["routes"]["chat"]["max_tokens"] = 0
        config["profiles"]["kimi"]["timeout"] = True
        errors = llm_config.validate(config)
        self.assertEqual(len(errors), 4)
        self.assertIn(["routes", "chat", "temperature"], [error["field"] for error in errors])

    def test_rejects_bad_provider_url_and_type(self):
        config = built()
        config["providers"]["openrouter"]["base_url"] = "file:///etc"
        config["providers"]["openrouter"]["type"] = "other"
        self.assertEqual(len(llm_config.validate(config)), 2)

    def test_rejects_url_without_host(self):
        config = built()
        config["providers"]["openrouter"]["base_url"] = "https://"
        self.assertEqual(len(llm_config.validate(config)), 1)

    def test_rejects_non_object_params(self):
        config = built()
        config["profiles"]["kimi"]["params"] = [1]
        self.assertEqual(len(llm_config.validate(config)), 1)


class KeyHandlingTest(unittest.TestCase):
    def test_masked_config_holds_no_api_key(self):
        config = built()
        result = llm_config.masked(config)
        self.assertNotIn("1234", repr(result))
        self.assertTrue(result["providers"]["openrouter"]["api_key_set"])
        self.assertEqual(config["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")

    def test_placeholder_key_counts_as_missing(self):
        config = built()
        config["providers"]["openrouter"]["api_key"] = "YOUR_OPENROUTER_KEY"
        provider = llm_config.masked(config)["providers"]["openrouter"]
        self.assertFalse(provider["api_key_set"])

    def test_empty_key_field_keeps_stored_key(self):
        old = built()
        new = llm_config.masked(old)
        result = llm_config.with_stored_keys(new, old)
        self.assertEqual(result["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")

    def test_new_key_replaces_stored_key(self):
        old = built()
        new = copy.deepcopy(old)
        new["providers"]["openrouter"]["api_key"] = "sk-new"
        self.assertEqual(llm_config.with_stored_keys(new, old)["providers"]["openrouter"]["api_key"], "sk-new")

    def test_new_provider_without_key_gets_empty_key(self):
        old = built()
        new = copy.deepcopy(old)
        new["providers"]["local"] = {"type": "openai", "base_url": "http://localhost:11434/v1"}
        self.assertEqual(llm_config.with_stored_keys(new, old)["providers"]["local"]["api_key"], "")

    def test_renamed_provider_keeps_stored_key(self):
        old = built()
        new = llm_config.masked(old)
        new["providers"]["or"] = dict(new["providers"].pop("openrouter"), previous_name="openrouter")
        result = llm_config.with_stored_keys(new, old)["providers"]["or"]
        self.assertEqual(result["api_key"], "sk-or-secret-1234")
        self.assertNotIn("previous_name", result)


class ProviderFromFormTest(unittest.TestCase):
    def test_empty_key_uses_stored_key_with_saved_base_url(self):
        provider = {"type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key": ""}
        self.assertEqual(llm_config.provider_from_form("openrouter", provider, built())["api_key"], "sk-or-secret-1234")

    def test_changed_base_url_gets_no_stored_key(self):
        provider = {"type": "openai", "base_url": "https://openrouter.ai.typo/api/v1", "api_key": ""}
        self.assertEqual(llm_config.provider_from_form("openrouter", provider, built())["api_key"], "")

    def test_typed_key_wins(self):
        provider = {"type": "openai", "base_url": "https://elsewhere.example/v1", "api_key": "sk-typed"}
        self.assertEqual(llm_config.provider_from_form("openrouter", provider, built())["api_key"], "sk-typed")

    def test_renamed_provider_uses_key_of_previous_name(self):
        provider = {"type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key": "", "previous_name": "openrouter"}
        result = llm_config.provider_from_form("or", provider, built())
        self.assertEqual(result["api_key"], "sk-or-secret-1234")
        self.assertNotIn("previous_name", result)


class ResetTest(unittest.TestCase):
    def setUp(self):
        self.defaults = llm_config.build(
            {"openrouter": {"api_key": "YOUR_OPENROUTER_KEY", "base_url": "https://openrouter.ai/api/v1"},
             "player2": {"api_key": "sk-player2-local", "base_url": "http://127.0.0.1:4315/v1", "game_key": ""}},
            {"player2-default": {"provider": "player2", "model": "default"}},
            "player2-default")

    def test_stored_key_of_default_provider_survives(self):
        self.assertEqual(llm_config.reset(self.defaults, built())["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")

    def test_placeholder_key_never_replaces_stored_key(self):
        old = built()
        old["providers"]["openrouter"]["api_key"] = "YOUR_OPENROUTER_KEY"
        self.assertEqual(llm_config.reset(self.defaults, old)["providers"]["openrouter"]["api_key"], "YOUR_OPENROUTER_KEY")

    def test_key_of_custom_host_is_dropped(self):
        old = built()
        old["providers"]["openrouter"]["base_url"] = "https://proxy.example/v1"
        self.assertEqual(llm_config.reset(self.defaults, old)["providers"]["openrouter"]["api_key"], "YOUR_OPENROUTER_KEY")

    def test_added_providers_and_profiles_go(self):
        result = llm_config.reset(self.defaults, built())
        self.assertEqual(set(result["providers"]), {"openrouter", "player2"})
        self.assertEqual(set(result["profiles"]), {"player2-default"})
        self.assertEqual(llm_config.validate(result), [])


class ModelIdsTest(unittest.TestCase):
    def test_reads_sorted_unique_ids(self):
        listing = {"object": "list", "data": [{"id": "b"}, {"id": "a"}, {"id": "b"}, {"name": "no id"}, "text"]}
        self.assertEqual(llm_config.model_ids(listing), ["a", "b"])

    def test_reply_without_data_has_no_ids(self):
        self.assertEqual(llm_config.model_ids({"error": "nope"}), [])
        self.assertEqual(llm_config.model_ids(["a"]), [])


class Player2InUseTest(unittest.TestCase):
    def test_lists_player2_providers_only_when_a_route_uses_them(self):
        config = built()
        self.assertEqual(llm_config.player2_providers_in_use(config), [])
        config["routes"]["ambient"]["profiles"].append("player2-default")
        self.assertEqual(llm_config.player2_providers_in_use(config), ["player2"])

    def test_default_slot_counts_as_its_profile(self):
        config = built()
        config["default_profile"] = "player2-default"
        self.assertEqual(llm_config.player2_providers_in_use(config), ["player2"])


class SaveTest(unittest.TestCase):
    def test_save_round_trips_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "user", "llm_config.json")
            llm_config.save(path, built())
            self.assertEqual(llm_config.load(path), built())
            self.assertEqual(os.listdir(os.path.dirname(path)), ["llm_config.json"])

    def test_failed_save_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "llm_config.json")
            llm_config.save(path, built())
            with self.assertRaises(TypeError):
                llm_config.save(path, {"providers": object()})
            self.assertEqual(llm_config.load(path), built())
            self.assertEqual(os.listdir(folder), ["llm_config.json"])


if __name__ == "__main__":
    unittest.main()
