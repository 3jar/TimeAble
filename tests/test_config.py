"""환경설정 테스트. Supabase env 미설정 시 미구성으로 인식해야 한다."""

import unittest

from timeable.api.config import Settings, supabase_configured


class ConfigTest(unittest.TestCase):
    def test_unset_is_not_configured(self):
        s = Settings(supabase_url=None, supabase_service_role_key=None)
        self.assertFalse(supabase_configured(s))

    def test_both_set_is_configured(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key="k")
        self.assertTrue(supabase_configured(s))

    def test_url_only_is_not_configured(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key=None)
        self.assertFalse(supabase_configured(s))


if __name__ == "__main__":
    unittest.main()
