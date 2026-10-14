from datetime import UTC, datetime

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dmag_crm.models.res_partner import normalize_vn_phone

from .dmag_conversation import channel_badge

CALL_STATE_SELECTION = [
    ('ringing', 'Đang đổ chuông'),
    ('answered', 'Đang nói chuyện'),
    ('done', 'Đã nghe máy'),
    ('missed', 'Gọi nhỡ'),
    ('no_answer', 'Khách không nghe'),
    ('busy', 'Máy bận'),
    ('failed', 'Lỗi'),
]
ENDED_STATES = ('done', 'missed', 'no_answer', 'busy', 'failed')


def _number(value):
    if isinstance(value, dict):
        return str(value.get('number') or value.get('alias') or '')
    return str(value or '')


def _ts(value):
    """Stringee gửi thời gian dạng mili-giây (hoặc giây). Trả về datetime UTC không múi giờ."""
    if not value:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number > 1e11:
        number /= 1000.0
    return datetime.fromtimestamp(number, UTC).replace(tzinfo=None)


class DmagCall(models.Model):
    _name = 'dmag.call'
    _description = 'Cuộc gọi'
    _order = 'date_start desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    account_id = fields.Many2one('dmag.channel.account', string='Tổng đài', index=True)
    external_id = fields.Char('Mã cuộc gọi Stringee', index=True, copy=False)
    direction = fields.Selection([('in', 'Gọi vào'), ('out', 'Gọi ra')], required=True, default='out')
    from_number = fields.Char('Số gọi')
    to_number = fields.Char('Số nhận')
    customer_number = fields.Char('Số khách', compute='_compute_customer_number', store=True)
    user_id = fields.Many2one('res.users', string='Nhân viên', index=True)
    partner_id = fields.Many2one('res.partner', string='Liên hệ', index=True)
    lead_id = fields.Many2one('crm.lead', string='Lead / cơ hội', index=True)
    state = fields.Selection(CALL_STATE_SELECTION, default='ringing', required=True)
    date_start = fields.Datetime('Bắt đầu', default=fields.Datetime.now)
    date_answer = fields.Datetime('Nghe máy')
    date_end = fields.Datetime('Kết thúc')
    duration = fields.Integer('Thời lượng (giây)')
    duration_display = fields.Char('Thời lượng', compute='_compute_duration_display')
    recording_url = fields.Char('Ghi âm')
    note = fields.Text('Ghi chú cuộc gọi')
    mail_message_id = fields.Many2one('mail.message', ondelete='set null')

    _external_uniq = models.Constraint('unique(account_id, external_id)', 'Mã cuộc gọi đã tồn tại.')

    @api.depends('direction', 'customer_number', 'date_start')
    def _compute_name(self):
        for call in self:
            arrow = _('Gọi vào') if call.direction == 'in' else _('Gọi ra')
            call.name = f'{arrow} {call.customer_number or ""}'

    @api.depends('direction', 'from_number', 'to_number')
    def _compute_customer_number(self):
        for call in self:
            call.customer_number = call.from_number if call.direction == 'in' else call.to_number

    @api.depends('duration')
    def _compute_duration_display(self):
        for call in self:
            minutes, seconds = divmod(call.duration or 0, 60)
            call.duration_display = f'{minutes:02d}:{seconds:02d}'

    # ------------------------------------------------------------------
    # Nhận sự kiện từ Stringee
    # ------------------------------------------------------------------
    @api.model
    def _dmag_from_stringee_event(self, account, payload):
        call_id = payload.get('call_id') or payload.get('callId') or payload.get('uuid')
        if not call_id:
            return self.browse()
        status = str(payload.get('call_status') or payload.get('callStatus') or payload.get('type') or '').lower()
        call = self.search([('account_id', '=', account.id), ('external_id', '=', call_id)], limit=1)
        from_number = _number(payload.get('from'))
        to_number = _number(payload.get('to'))
        if not call:
            hotline = normalize_vn_phone(account.stringee_hotline)
            outbound = bool(payload.get('fromInternal')) or (hotline and normalize_vn_phone(from_number) == hotline
                                                              and not payload.get('to_internal'))
            call = self.create({
                'account_id': account.id,
                'external_id': call_id,
                'direction': 'out' if outbound else 'in',
                'from_number': from_number,
                'to_number': to_number,
                'date_start': _ts(payload.get('start_time') or payload.get('timestamp_ms')) or fields.Datetime.now(),
                'user_id': account.user_id.id,
            })
            call._dmag_link_customer()
        vals = {}
        if status in ('answered', 'answer', 'talking'):
            vals.update({'state': 'answered',
                         'date_answer': _ts(payload.get('answer_time') or payload.get('timestamp_ms')) or fields.Datetime.now()})
        elif status in ('ended', 'end', 'hangup', 'stopped', 'completed', 'busy', 'failed'):
            answered = call.state == 'answered' or call.date_answer or payload.get('answer_time')
            if status == 'busy':
                state = 'busy'
            elif status == 'failed':
                state = 'failed'
            elif answered:
                state = 'done'
            else:
                state = 'missed' if call.direction == 'in' else 'no_answer'
            date_end = _ts(payload.get('stop_time') or payload.get('end_time') or payload.get('timestamp_ms')) or fields.Datetime.now()
            duration = payload.get('duration') or payload.get('answer_duration')
            if duration is None and (call.date_answer or payload.get('answer_time')):
                start = call.date_answer or _ts(payload.get('answer_time'))
                duration = (date_end - start).total_seconds()
            vals.update({'state': state, 'date_end': date_end, 'duration': int(float(duration or 0))})
            recording = payload.get('recording_url') or payload.get('record_url')
            if not recording and (payload.get('recorded') or payload.get('record')) and state == 'done':
                recording = account._stringee_recording_url(call_id)
            if recording:
                vals['recording_url'] = recording
        elif status in ('ringing', 'created', 'started'):
            vals['state'] = call.state if call.state != 'ringing' else 'ringing'
        if vals:
            call.write(vals)
        if call.state in ENDED_STATES:
            call._dmag_post_to_timeline()
        return call

    def _dmag_link_customer(self):
        Partner = self.env['res.partner']
        Lead = self.env['crm.lead']
        for call in self:
            partner = Partner._dmag_match_phone(call.customer_number)
            if not partner and call.direction == 'in' and call.account_id.auto_create_lead and call.customer_number:
                partner = Partner.create({'name': _('Khách gọi %s', call.customer_number), 'phone': call.customer_number})
            lead = call.lead_id or Lead._dmag_find_open_for_partner(partner)
            if not lead and partner and call.direction == 'in' and call.account_id.auto_create_lead:
                lead = Lead._dmag_create_from_channel(call.account_id, partner, partner.name)
            owner = partner.commercial_partner_id.dmag_account_owner_id if partner else False
            call.write({
                'partner_id': partner.id if partner else False,
                'lead_id': lead.id if lead else False,
                'user_id': call.user_id.id or (lead.user_id.id if lead else False) or (owner.id if owner else False),
            })

    def _dmag_timeline_body(self):
        self.ensure_one()
        labels = dict(CALL_STATE_SELECTION)
        arrow = '⬅' if self.direction == 'in' else '➡'
        body = Markup('%s %s <b>%s</b> · %s · %s') % (
            channel_badge('stringee'), arrow, self.customer_number or '', labels.get(self.state), self.duration_display)
        if self.user_id:
            body += Markup(' · %s') % self.user_id.name
        if self.recording_url:
            body += Markup('<br/><a href="%s" target="_blank" rel="noopener">▶ %s</a>') % (
                self.recording_url, _('Nghe ghi âm'))
        if self.note:
            body += Markup('<br/><i>%s</i>') % self.note
        return body

    def _dmag_post_to_timeline(self):
        for call in self:
            if not call.lead_id or call.mail_message_id:
                continue
            call.mail_message_id = call.lead_id.with_context(mail_create_nosubscribe=True).message_post(
                body=call._dmag_timeline_body(),
                message_type='comment',
                subtype_xmlid='dmag_omnichannel.mt_call',
                author_id=call.user_id.partner_id.id if call.user_id else None,
            )
            if call.state == 'missed':
                call.lead_id.activity_schedule(
                    'mail.mail_activity_data_call',
                    summary=_('Gọi lại khách gọi nhỡ %s', call.customer_number),
                    user_id=(call.lead_id.user_id or call.user_id or self.env.user).id,
                )

    def action_open_lead(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(_('Cuộc gọi chưa gắn lead.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': self.lead_id.id, 'view_mode': 'form'}
