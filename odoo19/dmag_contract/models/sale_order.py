from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dmag_contract_ids = fields.One2many('dmag.contract', 'sale_order_id', string='Hợp đồng')
    dmag_contract_count = fields.Integer(compute='_compute_dmag_contract_count')

    def _compute_dmag_contract_count(self):
        for order in self:
            order.dmag_contract_count = len(order.dmag_contract_ids)

    def action_dmag_create_contract(self):
        self.ensure_one()
        contract = self.dmag_contract_ids[:1] or self.env['dmag.contract'].create({
            'sale_order_id': self.id,
            'partner_id': self.partner_id.commercial_partner_id.id,
            'lead_id': self.opportunity_id.id,
            'title': self.dmag_prescription_id.name or self.name,
            'user_id': (self.user_id or self.env.user).id,
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'dmag.contract', 'res_id': contract.id, 'view_mode': 'form'}

    def action_dmag_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_contract.action_dmag_contract')
        action['domain'] = [('sale_order_id', '=', self.id)]
        return action
