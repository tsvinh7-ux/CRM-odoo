from odoo import api, fields, models

from odoo.addons.dmag_crm.models.dmag_segment import TIER_SELECTION


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dmag_is_module = fields.Boolean('Là module DMAG')
    dmag_module_code = fields.Char('Mã module', help='Ví dụ M-T8-01. Các hình thức của cùng một module dùng chung mã.')
    dmag_pillar_id = fields.Many2one('dmag.pillar', string='Trụ cột xử lý')
    dmag_tier = fields.Selection(TIER_SELECTION, string='Hình thức triển khai')
    dmag_is_dda_deposit = fields.Boolean('Là phí cọc DDA')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _dmag_find_module(self, pillar, tier):
        return self.search([
            ('product_tmpl_id.dmag_is_module', '=', True),
            ('product_tmpl_id.dmag_pillar_id', '=', pillar.id),
            ('product_tmpl_id.dmag_tier', '=', tier),
            ('sale_ok', '=', True),
        ], limit=1)
