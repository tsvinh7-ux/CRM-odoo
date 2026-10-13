from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dmag_prescription_id = fields.Many2one('dmag.prescription', string='Đơn kê lộ trình', copy=False, index=True)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    dmag_tier = fields.Selection(related='product_id.product_tmpl_id.dmag_tier', string='Hình thức')
    dmag_pillar_id = fields.Many2one(related='product_id.product_tmpl_id.dmag_pillar_id', string='Trụ cột')
