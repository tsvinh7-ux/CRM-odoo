import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestWebhook(HttpCase):

    def test_facebook_webhook_endpoints(self):
        account = self.env['dmag.channel.account'].create({
            'name': 'FB hook', 'channel': 'facebook', 'fb_verify_token': 'verify-me', 'fb_app_secret': 'shh'})
        url = f'/dmag/webhook/facebook/{account.id}'
        response = self.url_open(f'{url}?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=42')
        self.assertEqual(response.text, '42')
        body = json.dumps({'entry': [{'messaging': [{'sender': {'id': 'PS-77'}, 'recipient': {'id': 'P'},
                                                      'timestamp': 1, 'message': {'mid': 'hook-1', 'text': 'Hi'}}]}]})
        signature = 'sha256=' + hmac.new(b'shh', body.encode(), hashlib.sha256).hexdigest()
        bad = self.url_open(f'{url}?token={account.webhook_token}', data=body,
                            headers={'X-Hub-Signature-256': 'sha256=bad', 'Content-Type': 'application/json'})
        self.assertEqual(bad.status_code, 403)
        ok = self.url_open(f'{url}?token={account.webhook_token}', data=body,
                           headers={'X-Hub-Signature-256': signature, 'Content-Type': 'application/json'})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(self.env['dmag.conversation.message'].search([('external_id', '=', 'hook-1')]))
        no_token = self.url_open(url, data=body, headers={'X-Hub-Signature-256': signature})
        self.assertEqual(no_token.status_code, 403)
