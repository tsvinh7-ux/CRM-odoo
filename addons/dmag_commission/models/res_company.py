from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    dmag_split_closer = fields.Float('Tỷ lệ chia: người chốt (%)', default=70.0)
    dmag_split_lead = fields.Float('Tỷ lệ chia: người tạo/chăm lead (%)', default=20.0)
    dmag_split_owner = fields.Float('Tỷ lệ chia: Account Owner (%)', default=10.0)
    dmag_payroll_code = fields.Char('Mã hạng mục lương', default='HOA_HONG')

