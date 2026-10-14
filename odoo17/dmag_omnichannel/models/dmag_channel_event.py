import json
import logging
from datetime import UTC, datetime

from odoo import api, fields, models


_logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


class DmagChannelEvent(models.Model):
    """Nhật ký mọi webhook nhận được: dùng để kiểm toán, chống trùng và xử lý lại khi lỗi."""
    _name = 'dmag.channel.event'
    _description = 'Sự kiện webhook đa kênh'
    _order = 'id desc'

    account_id = fields.Many2one('dmag.channel.account', required=True, index=True, ondelete='cascade')
    channel = fields.Selection(related='account_id.channel', store=True)
    payload = fields.Text('Dữ liệu gốc')
    state = fields.Selection([
        ('new', 'Mới'),
        ('done', 'Đã xử lý'),
        ('error', 'Lỗi'),
    ], default='new', required=True, index=True)
    error = fields.Text('Lỗi')
    attempts = fields.Integer('Số lần xử lý')
    processed_date = fields.Datetime('Xử lý lúc')

    @api.model
    def _dmag_receive(self, account, payload):
        if isinstance(account, int):
            account = self.env['dmag.channel.account'].sudo().browse(account)
        event = self.sudo().create({'account_id': account.id, 'payload': json.dumps(payload, ensure_ascii=False)})
        event._dmag_process()
        return event

    def _dmag_process(self):
        for event in self:
            event.attempts += 1
            try:
                with self.env.cr.savepoint():
                    payload = json.loads(event.payload or '{}')
                    getattr(event, f'_process_{event.channel}')(payload)
                event.write({'state': 'done', 'error': False, 'processed_date': fields.Datetime.now()})
            except Exception as exc:  # noqa: BLE001 - lưu lỗi để thử lại, không trả lỗi cho kênh
                _logger.exception('Xử lý webhook %s thất bại', event.id)
                event.write({'state': 'error', 'error': str(exc)})

    @api.model
    def _cron_retry(self):
        self.search([('state', '=', 'error'), ('attempts', '<', MAX_ATTEMPTS)], limit=200)._dmag_process()

    def action_retry(self):
        self._dmag_process()

    # ------------------------------------------------------------------
    # Bộ chuyển đổi từng kênh
    # ------------------------------------------------------------------
    def _process_facebook(self, payload):
        Conversation = self.env['dmag.conversation'].sudo()
        account = self.account_id.sudo()
        for entry in payload.get('entry', []):
            for item in entry.get('messaging', []):
                message = item.get('message')
                if not message:
                    continue
                is_echo = message.get('is_echo')
                customer = (item.get('recipient') if is_echo else item.get('sender') or {}).get('id')
                attachments = [a.get('payload', {}).get('url') for a in message.get('attachments', [])
                               if a.get('payload', {}).get('url')]
                Conversation._dmag_ingest(
                    account, customer, 'out' if is_echo else 'in', message.get('text'),
                    external_msg_id=message.get('mid'),
                    date=fields.Datetime.to_datetime(_from_ms(item.get('timestamp'))),
                    attachments=attachments,
                )

    def _process_zalo(self, payload):
        account = self.account_id.sudo()
        event_name = payload.get('event_name') or ''
        if event_name in ('follow', 'unfollow'):
            follower = (payload.get('follower') or {}).get('id')
            if follower:
                identity = self.env['dmag.conversation'].sudo()._dmag_get_identity(account, follower)
                identity.followed = event_name == 'follow'
            return
        if event_name.startswith('user_send_'):
            direction, customer = 'in', (payload.get('sender') or {}).get('id')
        elif event_name.startswith('oa_send_'):
            direction, customer = 'out', (payload.get('recipient') or {}).get('id')
        else:
            return
        if '_group_' in event_name or not customer:
            return
        message = payload.get('message') or {}
        attachments = [(a.get('payload') or {}).get('url') for a in message.get('attachments') or []
                       if (a.get('payload') or {}).get('url')]
        text = message.get('text')
        if not text and event_name == 'user_send_sticker':
            text = '[Sticker]'
        self.env['dmag.conversation'].sudo()._dmag_ingest(
            account, customer, direction, text,
            external_msg_id=message.get('msg_id'),
            date=fields.Datetime.to_datetime(_from_ms(payload.get('timestamp'))),
            attachments=attachments,
        )

    def _process_stringee(self, payload):
        self.env['dmag.call'].sudo()._dmag_from_stringee_event(self.account_id.sudo(), payload)


def _from_ms(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return datetime.fromtimestamp(number / 1000.0 if number > 1e11 else number, UTC).replace(tzinfo=None)
