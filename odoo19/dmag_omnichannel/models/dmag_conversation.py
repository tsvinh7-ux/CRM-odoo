import re
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError


from .dmag_channel_account import CHANNEL_SELECTION, REPLY_WINDOW_HOURS

PHONE_RE = re.compile(r'(?:\+?84|0)(?:[\s.\-]?\d){9}')
CHANNEL_BADGE = {
    'facebook': ('Facebook', 'text-bg-primary'),
    'zalo': ('Zalo', 'text-bg-info'),
    'stringee': ('Cuộc gọi', 'text-bg-success'),
}


def channel_badge(channel):
    label, css = CHANNEL_BADGE.get(channel, (channel, 'text-bg-secondary'))
    return Markup('<span class="badge rounded-pill %s">%s</span>') % (css, label)


class DmagConversation(models.Model):
    _name = 'dmag.conversation'
    _description = 'Hội thoại đa kênh'
    _inherit = ['mail.thread']
    _order = 'last_message_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    account_id = fields.Many2one('dmag.channel.account', string='Kênh', required=True, index=True)
    channel = fields.Selection(related='account_id.channel', store=True)
    identity_id = fields.Many2one('dmag.channel.identity', string='Khách trên kênh', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Liên hệ', index=True, tracking=True)
    lead_id = fields.Many2one('crm.lead', string='Lead / cơ hội', index=True, tracking=True)
    user_id = fields.Many2one('res.users', string='Phụ trách', tracking=True, domain=[('share', '=', False)])
    state = fields.Selection([
        ('open', 'Đang mở'),
        ('pending', 'Chờ khách'),
        ('closed', 'Đã đóng'),
    ], default='open', required=True, tracking=True)
    message_line_ids = fields.One2many('dmag.conversation.message', 'conversation_id', string='Tin nhắn')
    last_message_date = fields.Datetime('Tin gần nhất', index=True)
    last_message_preview = fields.Char('Nội dung gần nhất')
    unread_count = fields.Integer('Chưa đọc')
    reply_deadline = fields.Datetime('Hạn được nhắn chủ động',
                                     help='Facebook: 24 giờ, Zalo OA (tin tư vấn): 48 giờ kể từ tin cuối của khách.')
    can_reply = fields.Boolean(compute='_compute_can_reply')

    @api.depends('identity_id.name', 'channel')
    def _compute_name(self):
        labels = dict(CHANNEL_SELECTION)
        for conversation in self:
            conversation.name = f'{labels.get(conversation.channel, "")} · {conversation.identity_id.name or conversation.identity_id.external_id or ""}'

    @api.depends('reply_deadline')
    def _compute_can_reply(self):
        now = fields.Datetime.now()
        for conversation in self:
            conversation.can_reply = bool(conversation.reply_deadline and conversation.reply_deadline > now)

    # ------------------------------------------------------------------
    # Nhận tin
    # ------------------------------------------------------------------
    @api.model
    def _dmag_ingest(self, account, external_user_id, direction, text, external_msg_id=None, date=None,
                     attachments=None, profile=None):
        """Ghi một tin nhắn từ kênh vào CRM. Idempotent theo external_msg_id."""
        Message = self.env['dmag.conversation.message']
        if external_msg_id and Message.search_count([('account_id', '=', account.id),
                                                     ('external_id', '=', external_msg_id)]):
            return Message.browse()
        date = date or fields.Datetime.now()
        identity = self._dmag_get_identity(account, external_user_id, profile)
        conversation = self.search([('identity_id', '=', identity.id)], limit=1)
        if not conversation:
            conversation = self.create({
                'account_id': account.id,
                'identity_id': identity.id,
                'partner_id': identity.partner_id.id,
                'user_id': account.user_id.id,
            })
        if direction == 'in':
            conversation._dmag_learn_phone(text)
        lead = conversation._dmag_ensure_lead() if direction == 'in' else conversation.lead_id
        message = Message.create({
            'conversation_id': conversation.id,
            'direction': direction,
            'body': text or '',
            'attachment_urls': '\n'.join(attachments or []),
            'external_id': external_msg_id,
            'date': date,
            'state': 'received' if direction == 'in' else 'sent',
            'author_user_id': self.env.user.id if direction == 'out' and not self.env.su else False,
        })
        vals = {'last_message_date': date, 'last_message_preview': (text or _('[Tệp đính kèm]'))[:120]}
        if direction == 'in':
            vals.update({
                'unread_count': conversation.unread_count + 1,
                'reply_deadline': date + timedelta(hours=REPLY_WINDOW_HOURS.get(account.channel, 24)),
                'state': 'open',
            })
            identity.last_inbound_date = date
        conversation.write(vals)
        message._dmag_post_to_timeline(lead)
        return message

    @api.model
    def _dmag_get_identity(self, account, external_user_id, profile=None):
        Identity = self.env['dmag.channel.identity']
        identity = Identity.search([('account_id', '=', account.id), ('external_id', '=', external_user_id)], limit=1)
        if identity:
            return identity
        if profile is None:
            profile = {}
            fetch = getattr(account, f'_{account.channel}_fetch_profile', None)
            if fetch:
                profile = fetch(external_user_id) or {}
        name = profile.get('name') or _('Khách %(channel)s %(id)s', channel=dict(CHANNEL_SELECTION)[account.channel],
                                         id=external_user_id[-6:])
        partner = self.env['res.partner']._dmag_match_phone(profile.get('phone'))
        if not partner:
            partner = self.env['res.partner'].create({'name': name, 'phone': profile.get('phone')})
        return Identity.create({
            'account_id': account.id,
            'external_id': external_user_id,
            'name': name,
            'avatar_url': profile.get('avatar_url'),
            'partner_id': partner.id,
        })

    def _dmag_learn_phone(self, text):
        """Khách gửi SĐT trong tin nhắn: gắn vào liên hệ, hoặc nhập vào hồ sơ đã có cùng SĐT."""
        self.ensure_one()
        match = PHONE_RE.search(text or '')
        if not match:
            return
        phone = match.group(0)
        existing = self.env['res.partner']._dmag_match_phone(phone)
        partner = self.partner_id
        if existing and existing != partner and not existing.commercial_partner_id == partner.commercial_partner_id:
            # Liên hệ tạm tạo từ kênh chưa có dữ liệu gì khác → chuyển sang hồ sơ đã có.
            self.identity_id.partner_id = existing
            self.partner_id = existing
            if self.lead_id and not self.lead_id.partner_id.commercial_partner_id == existing.commercial_partner_id:
                self.lead_id = False
        elif partner and not partner.phone:
            partner.phone = phone

    def _dmag_ensure_lead(self):
        self.ensure_one()
        Lead = self.env['crm.lead']
        if self.lead_id and self.lead_id.active and self.lead_id.won_status != 'lost':
            return self.lead_id
        lead = Lead._dmag_find_open_for_partner(self.partner_id)
        if not lead and self.account_id.auto_create_lead:
            lead = Lead._dmag_create_from_channel(self.account_id, self.partner_id, self.identity_id.name)
        self.lead_id = lead
        if lead and not self.user_id:
            self.user_id = lead.user_id
        return lead

    # ------------------------------------------------------------------
    # Gửi tin
    # ------------------------------------------------------------------
    def _dmag_send_text(self, text):
        self.ensure_one()
        if not text:
            raise UserError(_('Nội dung tin nhắn trống.'))
        if not self.can_reply:
            raise UserError(_('Đã quá hạn nhắn chủ động của %(channel)s (khách chưa nhắn lại trong %(hours)s giờ). '
                              'Hãy gọi điện hoặc dùng tin mẫu ZNS.',
                              channel=dict(CHANNEL_SELECTION)[self.channel],
                              hours=REPLY_WINDOW_HOURS.get(self.channel, 24)))
        account = self.account_id
        if self.channel == 'facebook':
            external_id = account._facebook_send_text(self.identity_id.external_id, text)
        elif self.channel == 'zalo':
            external_id = account._zalo_send_text(self.identity_id.external_id, text)
        else:
            raise UserError(_('Kênh này không hỗ trợ nhắn tin.'))
        message = self.env['dmag.conversation.message'].create({
            'conversation_id': self.id,
            'direction': 'out',
            'body': text,
            'external_id': external_id,
            'date': fields.Datetime.now(),
            'state': 'sent',
            'author_user_id': self.env.user.id,
        })
        self.write({'last_message_date': message.date, 'last_message_preview': text[:120], 'unread_count': 0,
                    'state': 'pending'})
        message._dmag_post_to_timeline(self.lead_id)
        return message

    def action_mark_read(self):
        self.write({'unread_count': 0})

    def action_close(self):
        self.write({'state': 'closed', 'unread_count': 0})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_reply(self):
        self.ensure_one()
        self.action_mark_read()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.channel.reply',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_conversation_id': self.id},
        }

    def action_create_lead(self):
        for conversation in self.filtered(lambda c: not c.lead_id):
            conversation.lead_id = self.env['crm.lead']._dmag_create_from_channel(
                conversation.account_id, conversation.partner_id, conversation.identity_id.name)
            for message in conversation.message_line_ids.sorted('date'):
                message._dmag_post_to_timeline(conversation.lead_id)


class DmagConversationMessage(models.Model):
    _name = 'dmag.conversation.message'
    _description = 'Tin nhắn đa kênh'
    _order = 'date asc, id asc'

    conversation_id = fields.Many2one('dmag.conversation', required=True, ondelete='cascade', index=True)
    account_id = fields.Many2one(related='conversation_id.account_id', store=True, index=True)
    channel = fields.Selection(related='conversation_id.channel', store=True)
    direction = fields.Selection([('in', 'Khách gửi'), ('out', 'DMAG gửi')], required=True)
    body = fields.Text('Nội dung')
    attachment_urls = fields.Text('Tệp đính kèm (URL)')
    external_id = fields.Char('Mã tin trên kênh', index=True)
    date = fields.Datetime('Thời gian', required=True, default=fields.Datetime.now)
    author_user_id = fields.Many2one('res.users', string='Nhân viên gửi')
    state = fields.Selection([
        ('received', 'Đã nhận'),
        ('sent', 'Đã gửi'),
        ('seen', 'Khách đã xem'),
        ('failed', 'Lỗi'),
    ], default='received')
    error = fields.Char('Lỗi')
    mail_message_id = fields.Many2one('mail.message', string='Bản ghi trên dòng thời gian', ondelete='set null')

    def _dmag_timeline_body(self):
        self.ensure_one()
        arrow = '⬅' if self.direction == 'in' else '➡'
        who = self.conversation_id.identity_id.name if self.direction == 'in' else (
            self.author_user_id.name or _('DMAG'))
        body = Markup('%s %s <b>%s</b><br/>%s') % (channel_badge(self.channel), arrow, who,
                                                    Markup('<br/>').join(escape(self.body or '').split('\n')))
        for url in filter(None, (self.attachment_urls or '').split('\n')):
            body += Markup('<br/><a href="%s" target="_blank" rel="noopener">📎 %s</a>') % (url, _('Tệp đính kèm'))
        return body

    def _dmag_post_to_timeline(self, lead):
        """Ghi tin nhắn vào chatter của lead để có một dòng thời gian chung (tin nhắn, cuộc gọi, email, log thay đổi)."""
        for message in self:
            if not lead or message.mail_message_id:
                continue
            author = message.conversation_id.partner_id if message.direction == 'in' else message.author_user_id.partner_id
            mail_message = lead.with_context(mail_create_nosubscribe=True).message_post(
                body=message._dmag_timeline_body(),
                message_type='comment',
                subtype_xmlid='dmag_omnichannel.mt_channel_message',
                author_id=author.id if author else None,
            )
            message.mail_message_id = mail_message
