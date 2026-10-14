from odoo import fields, models


class DmagCommissionGenerate(models.TransientModel):
    _name = 'dmag.commission.generate'
    _description = 'Tạo bảng kê hoa hồng tháng'

    month = fields.Date('Tháng', required=True, default=fields.Date.today,
                        help='Chọn một ngày bất kỳ trong tháng cần chốt.')

    def action_generate(self):
        statements = self.env['dmag.commission.statement']._generate_for_month(self.month)
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_commission.action_dmag_commission_statement')
        action['domain'] = [('id', 'in', statements.ids)]
        return action
