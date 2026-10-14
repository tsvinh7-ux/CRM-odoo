import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DmagWebhook(http.Controller):
    """Điểm nhận webhook. Luôn trả 200 nhanh; việc xử lý và thử lại nằm ở dmag.channel.event."""

    def _account(self, account_id, channel, token=None, check_token=True):
        account = request.env['dmag.channel.account'].sudo().browse(account_id).exists()
        if not account or account.channel != channel or not account.active:
            return None
        if check_token and not account._check_token(token):
            return None
        return account

    @http.route('/dmag/webhook/facebook/<int:account_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def facebook_verify(self, account_id, **params):
        account = self._account(account_id, 'facebook', check_token=False)
        if account and params.get('hub.mode') == 'subscribe' and params.get('hub.verify_token') == account.fb_verify_token:
            return request.make_response(params.get('hub.challenge', ''))
        return request.make_response('forbidden', status=403)

    @http.route('/dmag/webhook/facebook/<int:account_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def facebook_event(self, account_id, **params):
        account = self._account(account_id, 'facebook', params.get('token'))
        raw = request.httprequest.get_data()
        if not account or not account._facebook_verify_signature(raw, request.httprequest.headers.get('X-Hub-Signature-256')):
            return request.make_response('forbidden', status=403)
        request.env['dmag.channel.event'].sudo()._dmag_receive(account, json.loads(raw or b'{}'))
        return request.make_response('EVENT_RECEIVED')

    @http.route('/dmag/webhook/zalo/<int:account_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def zalo_event(self, account_id, **params):
        account = self._account(account_id, 'zalo', params.get('token'))
        raw = request.httprequest.get_data()
        payload = json.loads(raw or b'{}')
        if not account or not account._zalo_verify_signature(raw, request.httprequest.headers.get('X-ZEvent-Signature'), payload):
            return request.make_response('forbidden', status=403)
        request.env['dmag.channel.event'].sudo()._dmag_receive(account, payload)
        return request.make_json_response({'error': 0})

    @http.route('/dmag/webhook/stringee/event/<int:account_id>', type='http', auth='public', methods=['POST'], csrf=False)
    def stringee_event(self, account_id, **params):
        account = self._account(account_id, 'stringee', params.get('token'))
        if not account:
            return request.make_response('forbidden', status=403)
        raw = request.httprequest.get_data()
        payload = json.loads(raw) if raw else dict(params)
        request.env['dmag.channel.event'].sudo()._dmag_receive(account, payload)
        return request.make_json_response({'r': 0})

    @http.route('/dmag/webhook/stringee/answer/<int:account_id>', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def stringee_answer(self, account_id, **params):
        account = self._account(account_id, 'stringee', params.get('token'))
        if not account:
            return request.make_response('forbidden', status=403)
        return request.make_json_response(account._stringee_answer_scco(params))
