from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        self.env['dmag.commission.line'].sudo()._create_from_partials(partials)
        return partials

    def unlink(self):
        lines = self.env['dmag.commission.line'].sudo().search([('partial_id', 'in', self.ids)])
        lines._create_clawbacks()
        return super().unlink()
