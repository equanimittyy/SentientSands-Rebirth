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


def migrated():
    return llm_config.migrate(PROVIDERS, MODELS, "kimi")


class MigrateTest(unittest.TestCase):
    def test_routes_every_task_to_the_old_current_model(self):
        config = migrated()
        self.assertEqual(set(config["routes"]), set(llm_config.TASKS))
        for route in config["routes"].values():
            self.assertEqual(route["profiles"], ["kimi"])
            self.assertEqual(route["deadline"], llm_config.DEFAULT_DEADLINE)
        self.assertEqual(config["routes"]["profile"]["max_tokens"], 1500)

    def test_keeps_keys_and_sets_provider_type_from_name(self):
        config = migrated()
        self.assertEqual(config["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")
        self.assertEqual(config["providers"]["openrouter"]["type"], "openai")
        self.assertEqual(config["providers"]["player2"]["type"], "player2")
        self.assertEqual(config["providers"]["player2"]["game_key"], "game")

    def test_skips_models_whose_provider_is_missing(self):
        self.assertNotIn("orphan", migrated()["profiles"])

    def test_falls_back_to_first_profile_for_unknown_current_model(self):
        config = llm_config.migrate(PROVIDERS, MODELS, "gone")
        self.assertEqual(config["routes"]["chat"]["profiles"], ["kimi"])

    def test_migrated_config_is_valid(self):
        self.assertEqual(llm_config.validate(migrated()), [])


class ValidateTest(unittest.TestCase):
    def test_rejects_profile_with_missing_provider(self):
        config = migrated()
        config["profiles"]["kimi"]["provider"] = "gone"
        self.assertTrue(any("gone" in error for error in llm_config.validate(config)))

    def test_rejects_route_with_missing_profile(self):
        config = migrated()
        config["routes"]["chat"]["profiles"] = ["gone"]
        self.assertTrue(any("gone" in error for error in llm_config.validate(config)))

    def test_rejects_missing_task_and_bad_numbers(self):
        config = migrated()
        del config["routes"]["ambient"]
        config["routes"]["chat"]["temperature"] = 3
        config["routes"]["chat"]["max_tokens"] = 0
        config["profiles"]["kimi"]["timeout"] = True
        errors = llm_config.validate(config)
        self.assertEqual(len(errors), 4)

    def test_rejects_bad_provider_url_and_type(self):
        config = migrated()
        config["providers"]["openrouter"]["base_url"] = "file:///etc"
        config["providers"]["openrouter"]["type"] = "other"
        self.assertEqual(len(llm_config.validate(config)), 2)

    def test_rejects_url_without_host(self):
        config = migrated()
        config["providers"]["openrouter"]["base_url"] = "https://"
        self.assertEqual(len(llm_config.validate(config)), 1)

    def test_rejects_non_object_params(self):
        config = migrated()
        config["profiles"]["kimi"]["params"] = [1]
        self.assertEqual(len(llm_config.validate(config)), 1)


class KeyHandlingTest(unittest.TestCase):
    def test_masked_config_holds_no_api_key(self):
        config = migrated()
        result = llm_config.masked(config)
        self.assertNotIn("sk-or-secret-1234", repr(result))
        self.assertEqual(result["providers"]["openrouter"]["api_key_hint"], "1234")
        self.assertEqual(config["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")

    def test_empty_key_field_keeps_stored_key(self):
        old = migrated()
        new = llm_config.masked(old)
        result = llm_config.with_stored_keys(new, old)
        self.assertEqual(result["providers"]["openrouter"]["api_key"], "sk-or-secret-1234")
        self.assertNotIn("api_key_hint", result["providers"]["openrouter"])

    def test_new_key_replaces_stored_key(self):
        old = migrated()
        new = copy.deepcopy(old)
        new["providers"]["openrouter"]["api_key"] = "sk-new"
        self.assertEqual(llm_config.with_stored_keys(new, old)["providers"]["openrouter"]["api_key"], "sk-new")

    def test_new_provider_without_key_gets_empty_key(self):
        old = migrated()
        new = copy.deepcopy(old)
        new["providers"]["local"] = {"type": "openai", "base_url": "http://localhost:11434/v1"}
        self.assertEqual(llm_config.with_stored_keys(new, old)["providers"]["local"]["api_key"], "")


class Player2InUseTest(unittest.TestCase):
    def test_lists_player2_providers_only_when_a_route_uses_them(self):
        config = migrated()
        self.assertEqual(llm_config.player2_providers_in_use(config), [])
        config["routes"]["ambient"]["profiles"].append("player2-default")
        self.assertEqual(llm_config.player2_providers_in_use(config), ["player2"])


class SaveTest(unittest.TestCase):
    def test_save_round_trips_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "user", "llm_config.json")
            llm_config.save(path, migrated())
            self.assertEqual(llm_config.load(path), migrated())
            self.assertEqual(os.listdir(os.path.dirname(path)), ["llm_config.json"])

    def test_failed_save_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "llm_config.json")
            llm_config.save(path, migrated())
            with self.assertRaises(TypeError):
                llm_config.save(path, {"providers": object()})
            self.assertEqual(llm_config.load(path), migrated())
            self.assertEqual(os.listdir(folder), ["llm_config.json"])


if __name__ == "__main__":
    unittest.main()
