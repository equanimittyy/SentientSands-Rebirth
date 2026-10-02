import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from llm_router import build_body, run_route

MESSAGES = [{"role": "user", "content": "Hi"}]


def config(profiles, deadline=55):
    return {
        "providers": {"p": {"type": "openai", "base_url": "https://example.test", "api_key": "k"}},
        "profiles": {
            name: {"provider": "p", "model": name, "timeout": 30, "params": {}} for name in ("a", "b", "c")
        },
        "routes": {"chat": {"profiles": profiles, "max_tokens": 100, "temperature": 0.5, "deadline": deadline}},
    }


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RunRouteTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_returns_first_profile_text(self):
        calls = []

        def send(provider, profile, body, timeout):
            calls.append(profile["model"])
            return "hello"

        self.assertEqual(run_route(config(["a", "b"]), "chat", MESSAGES, send), "hello")
        self.assertEqual(calls, ["a"])

    def test_falls_through_on_error_and_empty_completion(self):
        calls = []

        def send(provider, profile, body, timeout):
            calls.append(profile["model"])
            if profile["model"] == "a":
                raise RuntimeError("HTTP 500")
            if profile["model"] == "b":
                return "   "
            return "from c"

        self.assertEqual(run_route(config(["a", "b", "c"]), "chat", MESSAGES, send), "from c")
        self.assertEqual(calls, ["a", "b", "c"])

    def test_same_profile_twice_is_a_retry(self):
        calls = []

        def send(provider, profile, body, timeout):
            calls.append(profile["model"])
            if len(calls) == 1:
                raise TimeoutError("timed out")
            return "second try"

        self.assertEqual(run_route(config(["a", "a"]), "chat", MESSAGES, send), "second try")
        self.assertEqual(calls, ["a", "a"])

    def test_returns_none_when_every_profile_fails(self):
        def send(provider, profile, body, timeout):
            raise RuntimeError("down")

        self.assertIsNone(run_route(config(["a", "b"]), "chat", MESSAGES, send))
        self.assertIsNone(run_route(config([]), "chat", MESSAGES, send))
        self.assertIsNone(run_route(config(["a"]), "ambient", MESSAGES, send))

    def test_attempt_timeout_is_capped_by_time_left(self):
        clock = FakeClock()
        timeouts = []

        def send(provider, profile, body, timeout):
            timeouts.append(timeout)
            clock.now += 40
            raise TimeoutError("timed out")

        run_route(config(["a", "b", "c"], deadline=55), "chat", MESSAGES, send, clock=clock)
        self.assertEqual(timeouts, [30, 15])

    def test_default_slot_runs_the_default_profile(self):
        calls = []

        def send(provider, profile, body, timeout):
            calls.append(profile["model"])
            raise RuntimeError("down")

        route_config = dict(config(["a", None]), default_profile="b")
        run_route(route_config, "chat", MESSAGES, send)
        self.assertEqual(calls, ["a", "b"])

    def test_skips_unknown_profile(self):
        self.assertEqual(run_route(config(["gone", "a"]), "chat", MESSAGES, lambda *args: "ok"), "ok")


class BuildBodyTest(unittest.TestCase):
    def test_profile_params_override_route_sampling(self):
        route = {"max_tokens": 100, "temperature": 0.5}
        profile = {"model": "m", "params": {"temperature": 1.0, "reasoning": {"effort": "low"}}}
        body = build_body(route, profile, MESSAGES)
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["max_tokens"], 100)
        self.assertEqual(body["temperature"], 1.0)
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertEqual(body["messages"], MESSAGES)


if __name__ == "__main__":
    unittest.main()
