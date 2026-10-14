from odoo import api, fields, models

from odoo.addons.dmag_crm.models.res_partner import normalize_vn_phone


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dmag_identity_ids = fields.One2many('dmag.channel.identity', 'partner_id', string='Tài khoản trên kênh')
    dmag_conversation_count = fields.Integer(compute='_compute_dmag_channel_counts')
    dmag_call_count = fields.Integer(compute='_compute_dmag_channel_counts')

    def _compute_dmag_channel_counts(self):
        Conversation = self.env['dmag.conversation']
        Call = self.env['dmag.call']
        for partner in self:
            family = partner | partner.child_ids if partner.is_company else partner
            partner.dmag_conversation_count = Conversation.search_count([('partner_id', 'in', family.ids)])
            partner.dmag_call_count = Call.search_count([('partner_id', 'in', family.ids)])

    @api.model
    def _dmag_match_phone(self, phone):
        """Tìm liên hệ theo SĐT đã chuẩn hoá; ưu tiên người liên hệ của phòng khám, sau đó tới phòng khám."""
        key = normalize_vn_phone(phone) if phone else False
        if not key:
            return self.browse()
        partners = self.search([('dmag_phone_key', '=', key)], order='is_company asc, id asc')
        return partners[:1]

    def action_dmag_view_conversations(self):
        self.ensure_one()
        family = self | self.child_ids if self.is_company else self
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_conversation')
        action['domain'] = [('partner_id', 'in', family.ids)]
        return action

    def action_dmag_view_calls(self):
        self.ensure_one()
        family = self | self.child_ids if self.is_company else self
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_omnichannel.action_dmag_call')
        action['domain'] = [('partner_id', 'in', family.ids)]
        return action
