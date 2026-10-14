from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dmag_contract_count = fields.Integer(compute='_compute_dmag_contract_count')

    def _compute_dmag_contract_count(self):
        Contract = self.env['dmag.contract']
        for partner in self:
            partner.dmag_contract_count = Contract.search_count([('partner_id', '=', partner.commercial_partner_id.id)])

    def action_dmag_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_contract.action_dmag_contract')
        action['domain'] = [('partner_id', '=', self.commercial_partner_id.id)]
        return action
