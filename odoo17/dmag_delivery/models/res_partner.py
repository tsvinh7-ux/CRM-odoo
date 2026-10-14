from odoo import fields, models

from .dmag_delivery_plan import PULSE_SELECTION


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dmag_delivery_plan_ids = fields.One2many('dmag.delivery.plan', 'partner_id', string='Lộ trình triển khai')
    dmag_delivery_plan_count = fields.Integer(compute='_compute_dmag_pulse')
    dmag_pulse = fields.Selection(PULSE_SELECTION, string='Pulse hiện tại', compute='_compute_dmag_pulse')

    def _compute_dmag_pulse(self):
        for partner in self:
            plans = partner.dmag_delivery_plan_ids
            partner.dmag_delivery_plan_count = len(plans)
            active = plans.filtered(lambda p: p.state == 'active').sorted('pulse_rank', reverse=True)
            partner.dmag_pulse = active[:1].pulse or False

    def action_dmag_view_delivery_plans(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_delivery.action_dmag_delivery_plan')
        action['domain'] = [('partner_id', '=', self.id)]
        return action
