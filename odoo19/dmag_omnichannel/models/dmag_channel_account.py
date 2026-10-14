import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CHANNEL_SELECTION = [
    ('facebook', 'Facebook Messenger'),
    ('zalo', 'Zalo OA'),
    ('stringee', 'Stringee (tổng đài)'),
]
TIMEOUT = 20
FB_GRAPH = 'https://graph.facebook.com/v21.0'
ZALO_OAUTH = 'https://oauth.zaloapp.com/v4/oa/access_token'
ZALO_API = 'https://openapi.zalo.me'
STRINGEE_API = 'https://api.stringee.com'

# Cửa sổ được phép nhắn chủ động sau tin cuối của khách.
REPLY_WINDOW_HOURS = {'facebook': 24, 'zalo': 48}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class DmagChannelAccount(models.Model):
    """Một kết nối kênh: một Fanpage, một Zalo OA hoặc một project Stringee.

    Mỗi kênh có các hàm _<kênh>_* riêng (adapter). Khi cần tách ra gateway riêng
    chỉ phải thay các hàm này, phần CRM không đổi.
    """
    _name = 'dmag.channel.account'
    _description = 'Kết nối kênh liên hệ'
    _inherit = ['mail.thread']

    name = fields.Char('Tên kết nối', required=True)
    channel = fields.Selection(CHANNEL_SELECTION, required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    team_id = fields.Many2one('crm.team', string='Pipeline nhận lead mới',
                              default=lambda self: self.env.ref('dmag_crm.team_diagnosis', raise_if_not_found=False))
    user_id = fields.Many2one('res.users', string='Người nhận mặc định', domain=[('share', '=', False)])
    auto_create_lead = fields.Boolean('Tự tạo lead khi khách mới nhắn/gọi', default=True)
    webhook_token = fields.Char('Mã bảo vệ webhook', copy=False, groups='dmag_crm.group_dmag_manager',
                                default=lambda self: _b64url(hashlib.sha256(str(time.time_ns()).encode()).digest())[:32])
    webhook_url = fields.Char('URL webhook', compute='_compute_webhook_url')

    # Facebook
    fb_page_id = fields.Char('Facebook Page ID')
    fb_page_token = fields.Char('Page Access Token', groups='dmag_crm.group_dmag_manager')
    fb_app_secret = fields.Char('App Secret', groups='dmag_crm.group_dmag_manager')
    fb_verify_token = fields.Char('Verify Token', groups='dmag_crm.group_dmag_manager')

    # Zalo OA
    zalo_app_id = fields.Char('Zalo App ID')
    zalo_oa_id = fields.Char('Zalo OA ID')
    zalo_secret_key = fields.Char('App Secret Key', groups='dmag_crm.group_dmag_manager')
    zalo_oa_secret = fields.Char('OA Secret Key (xác thực webhook)', groups='dmag_crm.group_dmag_manager')
    zalo_access_token = fields.Char('Access Token', groups='dmag_crm.group_dmag_manager')
    zalo_refresh_token = fields.Char('Refresh Token', groups='dmag_crm.group_dmag_manager')
    zalo_token_expiry = fields.Datetime('Access Token hết hạn')

    # Stringee
    stringee_key_sid = fields.Char('API Key SID')
    stringee_key_secret = fields.Char('API Key Secret', groups='dmag_crm.group_dmag_manager')
    stringee_hotline = fields.Char('Số hotline (định dạng 84…)')

    conversation_count = fields.Integer(compute='_compute_counts')
    call_count = fields.Integer(compute='_compute_counts')

    def _compute_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for account in self:
            if not account.id:
                account.webhook_url = False
                continue
            token = account.sudo().webhook_token
            path = {'facebook': 'facebook', 'zalo': 'zalo', 'stringee': 'stringee/event'}.get(account.channel, '')
            account.webhook_url = f'{base}/dmag/webhook/{path}/{account.id}?token={token}'

    def _compute_counts(self):
        for account in self:
            account.conversation_count = self.env['dmag.conversation'].search_count([('account_id', '=', account.id)])
            account.call_count = self.env['dmag.call'].search_count([('account_id', '=', account.id)])

    def _check_token(self, token):
        self.ensure_one()
        expected = self.sudo().webhook_token or ''
        return bool(token) and hmac.compare_digest(expected, token)

    # ------------------------------------------------------------------
    # Facebook Messenger
    # ------------------------------------------------------------------
    def _facebook_verify_signature(self, raw_body, header):
        self.ensure_one()
        secret = self.sudo().fb_app_secret
        if not secret:
            return True
        if not header or not header.startswith('sha256='):
            return False
        digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, header[7:])

    def _facebook_send_text(self, recipient_id, text):
        self.ensure_one()
        response = requests.post(
            f'{FB_GRAPH}/me/messages',
            params={'access_token': self.sudo().fb_page_token},
            json={'recipient': {'id': recipient_id}, 'messaging_type': 'RESPONSE', 'message': {'text': text}},
            timeout=TIMEOUT,
        )
        data = response.json()
        if response.status_code >= 400 or data.get('error'):
            raise UserError(_('Facebook từ chối gửi tin: %s', data.get('error', {}).get('message') or response.text))
        return data.get('message_id')

    def _facebook_fetch_profile(self, psid):
        self.ensure_one()
        if not self.sudo().fb_page_token:
            return {}
        try:
            response = requests.get(f'{FB_GRAPH}/{psid}', timeout=TIMEOUT, params={
                'fields': 'first_name,last_name,profile_pic', 'access_token': self.sudo().fb_page_token})
            data = response.json()
        except (requests.RequestException, ValueError):
            return {}
        name = ' '.join(filter(None, [data.get('last_name'), data.get('first_name')]))
        return {'name': name, 'avatar_url': data.get('profile_pic')}

    # ------------------------------------------------------------------
    # Zalo OA
    # ------------------------------------------------------------------
    def _zalo_verify_signature(self, raw_body, header, payload):
        """X-ZEvent-Signature = 'mac=' + sha256(app_id + body + timestamp + OA secret).

        Bỏ qua kiểm tra khi chưa nhập OA Secret. Công thức cần đối chiếu lại với tài liệu Zalo khi kết nối thật.
        """
        self.ensure_one()
        secret = self.sudo().zalo_oa_secret
        if not secret:
            return True
        if not header:
            return False
        raw = f'{payload.get("app_id", "")}{raw_body.decode()}{payload.get("timestamp", "")}{secret}'
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return hmac.compare_digest(digest, header.replace('mac=', ''))

    def _zalo_get_token(self):
        self.ensure_one()
        account = self.sudo()
        if account.zalo_access_token and account.zalo_token_expiry and account.zalo_token_expiry > fields.Datetime.now():
            return account.zalo_access_token
        if not account.zalo_refresh_token:
            raise UserError(_('Zalo OA "%s" chưa có Refresh Token.', account.name))
        response = requests.post(ZALO_OAUTH, timeout=TIMEOUT, headers={'secret_key': account.zalo_secret_key or ''}, data={
            'refresh_token': account.zalo_refresh_token, 'app_id': account.zalo_app_id, 'grant_type': 'refresh_token'})
        data = response.json()
        if not data.get('access_token'):
            raise UserError(_('Không làm mới được token Zalo: %s', data.get('error_description') or data))
        account.write({
            'zalo_access_token': data['access_token'],
            'zalo_refresh_token': data.get('refresh_token') or account.zalo_refresh_token,
            'zalo_token_expiry': fields.Datetime.now() + timedelta(seconds=int(data.get('expires_in', 3600)) - 300),
        })
        return data['access_token']

    def _zalo_send_text(self, user_id, text):
        self.ensure_one()
        response = requests.post(
            f'{ZALO_API}/v3.0/oa/message/cs', timeout=TIMEOUT,
            headers={'access_token': self._zalo_get_token(), 'Content-Type': 'application/json'},
            json={'recipient': {'user_id': user_id}, 'message': {'text': text}},
        )
        data = response.json()
        if data.get('error'):
            raise UserError(_('Zalo từ chối gửi tin (mã %(code)s): %(msg)s', code=data.get('error'), msg=data.get('message')))
        return (data.get('data') or {}).get('message_id')

    def _zalo_fetch_profile(self, user_id):
        self.ensure_one()
        if not (self.sudo().zalo_access_token or self.sudo().zalo_refresh_token):
            return {}
        try:
            response = requests.get(f'{ZALO_API}/v3.0/oa/user/detail', timeout=TIMEOUT,
                                    headers={'access_token': self._zalo_get_token()},
                                    params={'data': json.dumps({'user_id': user_id})})
            data = (response.json() or {}).get('data') or {}
        except (requests.RequestException, ValueError, UserError):
            return {}
        info = data.get('shared_info') or {}
        return {'name': data.get('display_name'), 'avatar_url': data.get('avatar'), 'phone': info.get('phone')}

    # ------------------------------------------------------------------
    # Stringee
    # ------------------------------------------------------------------
    def _stringee_rest_token(self, ttl=3600):
        """JWT HS256 cho REST API Stringee (header X-STRINGEE-AUTH)."""
        self.ensure_one()
        account = self.sudo()
        if not (account.stringee_key_sid and account.stringee_key_secret):
            raise UserError(_('Chưa cấu hình API Key của Stringee.'))
        now = int(time.time())
        header = {'typ': 'JWT', 'alg': 'HS256', 'cty': 'stringee-api;v=1'}
        claims = {'jti': f'{account.stringee_key_sid}-{now}', 'iss': account.stringee_key_sid,
                  'exp': now + ttl, 'rest_api': True}
        signing_input = f'{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}'
        signature = hmac.new(account.stringee_key_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        return f'{signing_input}.{_b64url(signature)}'

    def _stringee_callout(self, agent_user, customer_number):
        """Click-to-call: Stringee gọi cho nhân viên trước, nhân viên nhấc máy thì nối sang khách."""
        self.ensure_one()
        if agent_user.dmag_stringee_user_id:
            agent = {'type': 'internal', 'number': agent_user.dmag_stringee_user_id, 'alias': agent_user.name}
        elif agent_user.dmag_stringee_phone:
            agent = {'type': 'external', 'number': agent_user.dmag_stringee_phone, 'alias': agent_user.name}
        else:
            raise UserError(_('Người dùng %s chưa khai báo Stringee user ID hoặc số máy nhánh.', agent_user.name))
        hotline = {'type': 'external', 'number': self.stringee_hotline, 'alias': self.stringee_hotline}
        body = {
            'from': hotline,
            'to': [agent],
            'actions': [{'action': 'connect', 'from': hotline,
                         'to': {'type': 'external', 'number': customer_number, 'alias': customer_number}}],
        }
        response = requests.post(f'{STRINGEE_API}/v1/call2/callout', json=body, timeout=TIMEOUT,
                                 headers={'X-STRINGEE-AUTH': self._stringee_rest_token()})
        data = response.json()
        if data.get('r') not in (0, None) or response.status_code >= 400:
            raise UserError(_('Stringee từ chối cuộc gọi: %s', data.get('message') or data))
        return data.get('call_id') or data.get('callId')

    def _stringee_answer_scco(self, payload):
        """SCCO trả cho answer_url khi có cuộc gọi vào hotline: nối tới người phụ trách khách (nếu biết)."""
        self.ensure_one()
        caller = str(payload.get('from') or '')
        partner = self.env['res.partner']._dmag_match_phone(caller)
        owner = partner.commercial_partner_id.dmag_account_owner_id or partner.user_id or self.user_id
        target = owner.dmag_stringee_user_id if owner else False
        if target:
            to = {'type': 'internal', 'number': target, 'alias': owner.name}
        else:
            to = {'type': 'internal', 'number': self.user_id.dmag_stringee_user_id or '', 'alias': 'DMAG'}
        return [{'action': 'record', 'eventUrl': '', 'format': 'mp3'},
                {'action': 'connect', 'from': {'type': 'external', 'number': caller, 'alias': caller}, 'to': to}]

    def _stringee_recording_url(self, call_id):
        return f'{STRINGEE_API}/v1/call/play/{call_id}'

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_view_conversations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_conversation')
        action['domain'] = [('account_id', '=', self.id)]
        return action

    def action_view_calls(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_call')
        action['domain'] = [('account_id', '=', self.id)]
        return action

    def action_test_connection(self):
        self.ensure_one()
        if self.channel == 'zalo':
            self._zalo_get_token()
        elif self.channel == 'stringee':
            self._stringee_rest_token()
        elif self.channel == 'facebook':
            response = requests.get(f'{FB_GRAPH}/me', params={'access_token': self.sudo().fb_page_token}, timeout=TIMEOUT)
            if response.status_code >= 400:
                raise UserError(_('Page token không hợp lệ: %s', response.text))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'message': _('Kết nối "%s" hoạt động.', self.name)}}

    @api.model
    def _cron_refresh_zalo_tokens(self):
        soon = fields.Datetime.now() + timedelta(hours=1)
        for account in self.sudo().search([('channel', '=', 'zalo'), ('zalo_refresh_token', '!=', False),
                                           '|', ('zalo_token_expiry', '=', False), ('zalo_token_expiry', '<', soon)]):
            try:
                account.zalo_token_expiry = False
                account._zalo_get_token()
            except Exception as exc:  # noqa: BLE001 - ghi log, không làm hỏng cron
                _logger.warning('Không làm mới được token Zalo %s: %s', account.name, exc)
