import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


def _ms(offset=0):
    return int(time.time() * 1000) + offset


@tagged('post_install', '-at_install')
class TestOmnichannel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['dmag.channel.account']
        cls.fb = Account.create({'name': 'FB', 'channel': 'facebook', 'user_id': cls.env.user.id})
        cls.zalo = Account.create({'name': 'Zalo', 'channel': 'zalo', 'user_id': cls.env.user.id})
        cls.stringee = Account.create({'name': 'Hotline', 'channel': 'stringee', 'stringee_hotline': '842400000000',
                                       'stringee_key_sid': 'SK123', 'stringee_key_secret': 'secret'})
        cls.clinic = cls.env['res.partner'].create({
            'name': 'Omni Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0912 345 678'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Existing lead', 'type': 'opportunity', 'partner_id': cls.clinic.id,
            'team_id': cls.env.ref('dmag_crm.team_diagnosis').id})
        cls.Event = cls.env['dmag.channel.event']

    def _fb(self, psid, mid, text, echo=False):
        sender, recipient = ({'id': 'PAGE'}, {'id': psid}) if echo else ({'id': psid}, {'id': 'PAGE'})
        return self.Event._dmag_receive(self.fb, {'entry': [{'messaging': [{
            'sender': sender, 'recipient': recipient, 'timestamp': _ms(),
            'message': {'mid': mid, 'text': text, **({'is_echo': True} if echo else {})}}]}]})

    def test_facebook_message_links_existing_clinic_by_phone(self):
        event = self._fb('PSID-1', 'mid-1', 'Em cần tư vấn, số em 0912.345.678')
        self.assertEqual(event.state, 'done', event.error)
        conversation = self.env['dmag.conversation'].search([('account_id', '=', self.fb.id)])
        self.assertEqual(conversation.partner_id, self.clinic)
        self.assertEqual(conversation.lead_id, self.lead, 'Tin nhắn phải vào đúng lead đang mở của phòng khám')
        self.assertEqual(conversation.unread_count, 1)
        self.assertTrue(conversation.can_reply)
        timeline = self.lead.message_ids.filtered(
            lambda m: m.subtype_id == self.env.ref('dmag_omnichannel.mt_channel_message'))
        self.assertEqual(len(timeline), 1)
        self.assertIn('0912.345.678', timeline.body)
        # Tin echo do nhân viên gửi trên Fanpage cũng được ghi lại, chiều "out"
        self._fb('PSID-1', 'mid-2', 'Dạ DMAG gọi lại ngay', echo=True)
        self.assertEqual(conversation.message_line_ids.mapped('direction'), ['in', 'out'])
        # Webhook gửi lại cùng mid không tạo trùng
        self._fb('PSID-1', 'mid-1', 'Em cần tư vấn, số em 0912.345.678')
        self.assertEqual(len(conversation.message_line_ids), 2)

    def test_zalo_new_user_creates_lead(self):
        self.Event._dmag_receive(self.zalo, {'event_name': 'follow', 'timestamp': str(_ms()), 'follower': {'id': 'ZU-1'}})
        identity = self.env['dmag.channel.identity'].search([('external_id', '=', 'ZU-1')])
        self.assertTrue(identity.followed)
        self.Event._dmag_receive(self.zalo, {
            'event_name': 'user_send_text', 'timestamp': str(_ms()), 'sender': {'id': 'ZU-1'},
            'recipient': {'id': 'OA'}, 'message': {'msg_id': 'z1', 'text': 'Cho hỏi lịch hội thảo'}})
        conversation = self.env['dmag.conversation'].search([('identity_id', '=', identity.id)])
        lead = conversation.lead_id
        self.assertTrue(lead)
        self.assertEqual(lead.source_id, self.env.ref('dmag_omnichannel.utm_source_zalo'))
        self.assertEqual(lead.team_id, self.env.ref('dmag_crm.team_diagnosis'))
        self.assertEqual(lead.dmag_unread_count, 1)
        self.assertEqual(conversation.reply_deadline.date(), (fields.Datetime.now() + timedelta(hours=48)).date())

    def test_send_zalo_reply_and_window(self):
        self.zalo.write({'zalo_access_token': 'TOKEN', 'zalo_token_expiry': fields.Datetime.now() + timedelta(hours=5)})
        self.Event._dmag_receive(self.zalo, {
            'event_name': 'user_send_text', 'timestamp': str(_ms()), 'sender': {'id': 'ZU-9'},
            'recipient': {'id': 'OA'}, 'message': {'msg_id': 'z9', 'text': 'Xin chào'}})
        conversation = self.env['dmag.conversation'].search([('account_id', '=', self.zalo.id)])

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {'error': 0, 'data': {'message_id': 'out-1'}}

        with patch('odoo.addons.dmag_omnichannel.models.dmag_channel_account.requests.post',
                   return_value=FakeResponse()) as post:
            conversation._dmag_send_text('Dạ chào anh/chị')
        self.assertEqual(post.call_args.kwargs['json']['recipient']['user_id'], 'ZU-9')
        self.assertEqual(post.call_args.kwargs['headers']['access_token'], 'TOKEN')
        out = conversation.message_line_ids.filtered(lambda m: m.direction == 'out')
        self.assertEqual(out.external_id, 'out-1')
        self.assertTrue(out.mail_message_id)
        conversation.reply_deadline = fields.Datetime.now() - timedelta(minutes=1)
        with self.assertRaises(UserError):
            conversation._dmag_send_text('Tin quá hạn')

    def test_stringee_inbound_call_timeline(self):
        base = {'call_id': 'c1', 'from': {'number': '84912345678'}, 'to': {'number': '842400000000'}}
        self.Event._dmag_receive(self.stringee, dict(base, call_status='ringing', timestamp_ms=_ms(-200000)))
        self.Event._dmag_receive(self.stringee, {'call_id': 'c1', 'call_status': 'answered', 'timestamp_ms': _ms(-190000)})
        self.Event._dmag_receive(self.stringee, {'call_id': 'c1', 'call_status': 'ended', 'duration': 125,
                                                 'recording_url': 'https://rec/1.mp3', 'timestamp_ms': _ms()})
        call = self.env['dmag.call'].search([('external_id', '=', 'c1')])
        self.assertEqual(call.direction, 'in')
        self.assertEqual(call.state, 'done')
        self.assertEqual(call.duration_display, '02:05')
        self.assertEqual(call.partner_id, self.clinic)
        self.assertEqual(call.lead_id, self.lead)
        self.assertIn('https://rec/1.mp3', call.mail_message_id.body)
        self.assertEqual(self.lead.dmag_call_count, 1)

    def test_stringee_missed_call_creates_callback_activity(self):
        self.Event._dmag_receive(self.stringee, {'call_id': 'c2', 'call_status': 'ended',
                                                 'from': {'number': '0912345678'}, 'to': {'number': '842400000000'}})
        call = self.env['dmag.call'].search([('external_id', '=', 'c2')])
        self.assertEqual(call.state, 'missed')
        self.assertTrue(self.lead.activity_ids.filtered(lambda a: 'Gọi lại' in (a.summary or '')))

    def test_stringee_jwt(self):
        token = self.stringee._stringee_rest_token()
        header, claims, signature = token.split('.')
        pad = lambda s: s + '=' * (-len(s) % 4)  # noqa: E731
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(claims)))['iss'], 'SK123')
        expected = hmac.new(b'secret', f'{header}.{claims}'.encode(), hashlib.sha256).digest()
        self.assertEqual(base64.urlsafe_b64decode(pad(signature)), expected)

    def test_click_to_call_requires_agent_setup(self):
        with self.assertRaises(UserError):
            self.lead.action_dmag_call()

    def test_facebook_signature(self):
        self.fb.fb_app_secret = 'appsecret'
        body = b'{"entry": []}'
        good = 'sha256=' + hmac.new(b'appsecret', body, hashlib.sha256).hexdigest()
        self.assertTrue(self.fb._facebook_verify_signature(body, good))
        self.assertFalse(self.fb._facebook_verify_signature(body, 'sha256=bad'))

    def test_failed_event_is_kept_for_retry(self):
        event = self.Event._dmag_receive(self.zalo, {'event_name': 'user_send_text', 'sender': {'id': 'ZU-X'},
                                                     'message': {'msg_id': 'zx', 'text': 'x'}, 'timestamp': 'bad'})
        self.assertIn(event.state, ('done', 'error'))
        with patch.object(type(self.env['dmag.conversation']), '_dmag_ingest', side_effect=ValueError('boom')), \
                mute_logger('odoo.addons.dmag_omnichannel.models.dmag_channel_event'):
            failed = self.Event._dmag_receive(self.zalo, {'event_name': 'user_send_text', 'sender': {'id': 'ZU-Y'},
                                                         'message': {'msg_id': 'zy', 'text': 'y'}})
        self.assertEqual(failed.state, 'error')
        failed._dmag_process()
        self.assertEqual(failed.state, 'done')
        self.assertEqual(failed.attempts, 2)
