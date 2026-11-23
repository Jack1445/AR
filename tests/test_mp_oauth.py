import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import mp_oauth
import portal_data
from portal_server import Handler, oauth_role, oauth_state


class OAuthTests(unittest.TestCase):
    def test_proxy_healthcheck_does_not_require_public_host(self):
        from unittest.mock import Mock
        handler = Handler.__new__(Handler)
        handler.path = "/up"
        handler._allowed = Mock(side_effect=AssertionError("host check used"))
        handler._json = Mock()
        handler.do_GET()
        handler._json.assert_called_once_with(200, {"ok": True})

    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret"})
    def test_state_survives_process_restart_and_rejects_tampering(self):
        state = oauth_state("alumni")
        self.assertEqual(oauth_role(state), "alumni")
        self.assertIsNone(oauth_role("candidate" + state[len("alumni"):]))
        self.assertIsNone(oauth_role("alumni.0.nonce." + state.rsplit(".", 1)[1]))


    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret"})
    @patch("portal_server.login_with_mp")
    @patch("portal_server.mp_oauth.userinfo", return_value={"sub": "mp-user", "phone": "13800138000", "roles": ["founder"]})
    def test_alumni_without_founder_company_hr_is_rejected_before_account_binding(self, _userinfo, login_with_mp):
        state = oauth_state("alumni")
        handler = Handler.__new__(Handler)
        handler.path = "/oauth/callback?code=auth-code&state=" + state
        handler.headers = {"Cookie": "AR_OAUTH_STATE=" + state}
        handler._redirect = unittest.mock.Mock()

        handler._oauth_callback()

        handler._redirect.assert_called_once_with("/alumni/?auth_error=founder_company_hr_required")
        login_with_mp.assert_not_called()

    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret"})
    @patch("portal_server.account_data")
    @patch("portal_server.login_with_mp")
    @patch("portal_server.mp_oauth.userinfo", return_value={"sub": "mp-user", "phone": "13800138000", "roles": ["founder_company_hr"]})
    def test_alumni_founder_company_hr_can_login_without_founder(self, _userinfo, login_with_mp, account_data):
        state = oauth_state("alumni")
        handler = Handler.__new__(Handler)
        handler.path = "/oauth/callback?code=auth-code&state=" + state
        handler.headers = {"Cookie": "AR_OAUTH_STATE=" + state}
        handler._redirect = unittest.mock.Mock()
        sessions = {}

        with patch("portal_server.SESSIONS", sessions):
            handler._oauth_callback()

        login_with_mp.assert_called_once_with("alumni", "mp-user", "13800138000")
        account_data.assert_called_once_with(login_with_mp.return_value)
        self.assertEqual(handler._redirect.call_args.args[0], "/alumni/")
        self.assertTrue(handler._redirect.call_args.args[1].startswith("AR_PORTAL_SESSION="))
        self.assertEqual(len(sessions), 1)

    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret"})
    @patch("portal_server.account_data")
    @patch("portal_server.login_with_mp")
    @patch("portal_server.mp_oauth.userinfo", return_value={"sub": "mp-user", "phone": "", "roles": []})
    def test_candidate_invalid_phone_gets_specific_error(self, _userinfo, login_with_mp, _account_data):
        state = oauth_state("candidate")
        handler = Handler.__new__(Handler)
        handler.path = "/oauth/callback?code=auth-code&state=" + state
        handler.headers = {"Cookie": "AR_OAUTH_STATE=" + state}
        handler._redirect = unittest.mock.Mock()

        login_with_mp.side_effect = portal_data.MpLoginError("invalid_phone", "手机号无效")
        handler._oauth_callback()

        handler._redirect.assert_called_once_with("/candidate/?auth_error=invalid_phone")

    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret"})
    @patch("portal_server.account_data")
    @patch("portal_server.login_with_mp", side_effect=portal_data.MpLoginError("phone_in_use", "手机号已占用"))
    @patch("portal_server.mp_oauth.userinfo", return_value={"sub": "mp-user", "phone": "13800138000", "roles": []})
    def test_candidate_existing_phone_gets_specific_error(self, _userinfo, _login, _account_data):
        state = oauth_state("candidate")
        handler = Handler.__new__(Handler)
        handler.path = "/oauth/callback?code=auth-code&state=" + state
        handler.headers = {"Cookie": "AR_OAUTH_STATE=" + state}
        handler._redirect = unittest.mock.Mock()

        handler._oauth_callback()

        handler._redirect.assert_called_once_with("/candidate/?auth_error=phone_in_use")

    def test_cross_site_navigation_allowed_only_for_callback(self):
        handler = Handler.__new__(Handler)
        handler.headers = {"Host": "127.0.0.1:38480", "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"}
        handler.command = "GET"
        handler.path = "/oauth/callback?code=example"
        self.assertTrue(handler._allowed())
        handler.path = "/candidate/"
        self.assertTrue(handler._allowed())
        handler.path = "/api/candidate/me"
        self.assertFalse(handler._allowed())
        handler.path = "/oauth/callback"
        handler.command = "POST"
        self.assertFalse(handler._allowed())

    @patch.dict("os.environ", {"MP_OAUTH_URL": "http://127.0.0.1:3001", "MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret", "AR_PORTAL_ORIGIN": "http://127.0.0.1:38480"})
    def test_local_mp_callback(self):
        url = urlparse(mp_oauth.authorization_url("random-state"))
        self.assertEqual(url.netloc, "127.0.0.1:3001")
        self.assertEqual(parse_qs(url.query)["redirect_uri"], ["http://127.0.0.1:38480/oauth/callback"])

    @patch.dict("os.environ", {"MP_OAUTH_CLIENT_ID": "client", "MP_OAUTH_CLIENT_SECRET": "secret", "AR_PORTAL_ORIGIN": "https://talent.example.com"})
    def test_authorization_and_exchange(self):
        url = urlparse(mp_oauth.authorization_url("random-state"))
        self.assertEqual(url.path, "/oauth/authorize")
        self.assertEqual(parse_qs(url.query)["state"], ["random-state"])
        self.assertEqual(parse_qs(url.query)["redirect_uri"], ["https://talent.example.com/oauth/callback"])

        class Reply:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                return self.value

        requests = []

        def open_url(request, timeout):
            requests.append(request)
            return Reply(b'{"access_token":"access"}' if len(requests) == 1 else b'{"sub":"123","phone":"13800138000"}')

        with patch.object(mp_oauth.urllib.request, "urlopen", side_effect=open_url):
            self.assertEqual(mp_oauth.userinfo("auth-code")["sub"], "123")
        self.assertEqual(parse_qs(requests[0].data.decode())["code"], ["auth-code"])
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer access")


if __name__ == "__main__":
    unittest.main()
