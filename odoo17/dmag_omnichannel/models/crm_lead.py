from odoo import _, api, fields, models
from odoo.exceptions import UserError

UTM_SOURCE_BY_CHANNEL = {
    'facebook': 'utm.utm_source_facebook',
    'zalo': 'dmag_omnichannel.utm_source_zalo',
    'stringee': 'dmag_omnichannel.utm_source_hotline',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    dmag_conversation_ids = fields.One2many('dmag.conversation', 'lead_id', string='Hội thoại')
    dmag_call_ids = fields.One2many('dmag.call', 'lead_id', string='Cuộc gọi')
    dmag_conversation_count = fields.Integer(compute='_compute_dmag_channel_stats')
    dmag_call_count = fields.Integer(compute='_compute_dmag_channel_stats')
    dmag_unread_count = fields.Integer('Tin chưa đọc', compute='_compute_dmag_channel_stats')
    dmag_last_contact_date = fields.Datetime('Liên hệ gần nhất', compute='_compute_dmag_channel_stats')

    @api.depends('dmag_conversation_ids.unread_count', 'dmag_conversation_ids.last_message_date',
                 'dmag_call_ids.date_start')
    def _compute_dmag_channel_stats(self):
        for lead in self:
            lead.dmag_conversation_count = len(lead.dmag_conversation_ids)
            lead.dmag_call_count = len(lead.dmag_call_ids)
            lead.dmag_unread_count = sum(lead.dmag_conversation_ids.mapped('unread_count'))
            dates = [d for d in lead.dmag_conversation_ids.mapped('last_message_date') + lead.dmag_call_ids.mapped('date_start') if d]
            lead.dmag_last_contact_date = max(dates) if dates else False

    @api.model
    def _dmag_find_open_for_partner(self, partner):
        if not partner:
            return self.browse()
        company = partner.commercial_partner_id
        return self.search([
            ('partner_id', 'child_of', company.id),
            ('stage_id.is_won', '=', False),
            ('active', '=', True),
        ], order='create_date desc', limit=1)

    @api.model
    def _dmag_create_from_channel(self, account, partner, display_name):
        labels = dict(self.env['dmag.channel.account']._fields['channel'].selection)
        source = self.env.ref(UTM_SOURCE_BY_CHANNEL.get(account.channel, ''), raise_if_not_found=False)
        return self.create({
            'name': _('%(channel)s: %(name)s', channel=labels.get(account.channel), name=display_name or partner.name),
            'type': 'opportunity',
            'partner_id': partner.id if partner else False,
            'team_id': account.team_id.id,
            'user_id': account.user_id.id or (partner.commercial_partner_id.dmag_account_owner_id.id if partner else False),
            'source_id': source.id if source else False,
            'dmag_lead_owner_id': account.user_id.id or False,
        })

    # ------------------------------------------------------------------
    # Nút trên lead
    # ------------------------------------------------------------------
    def action_dmag_send_message(self):
        self.ensure_one()
        conversations = self.dmag_conversation_ids.sorted('last_message_date', reverse=True)
        if not conversations:
            raise UserError(_('Lead chưa có hội thoại Facebook/Zalo. Khách cần nhắn tới Page/OA trước.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.channel.reply',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_conversation_id': conversations[0].id, 'default_lead_id': self.id},
        }

    def action_dmag_call(self):
        self.ensure_one()
        number = self.phone or self.partner_id.phone or self.partner_id.commercial_partner_id.phone
        if not number:
            raise UserError(_('Lead chưa có số điện thoại.'))
        account = self.env['dmag.channel.account'].search([('channel', '=', 'stringee')], limit=1)
        if not account:
            raise UserError(_('Chưa cấu hình kết nối Stringee.'))
        call_id = account._stringee_callout(self.env.user, number)
        call = self.env['dmag.call'].create({
            'account_id': account.id,
            'external_id': call_id,
            'direction': 'out',
            'from_number': account.stringee_hotline,
            'to_number': number,
            'user_id': self.env.user.id,
            'partner_id': self.partner_id.id,
            'lead_id': self.id,
        })
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'info', 'sticky': False,
                           'message': _('Stringee đang gọi cho bạn, nhấc máy để nối tới %s.', number)},
                'context': {'dmag_call_id': call.id}}

    def action_dmag_view_conversations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_conversation')
        action['domain'] = [('lead_id', '=', self.id)]
        return action

    def action_dmag_view_calls(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_call')
        action['domain'] = [('lead_id', '=', self.id)]
        return action
