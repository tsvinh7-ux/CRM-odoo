from odoo import api, fields, models


class DmagPillar(models.Model):
    _name = 'dmag.pillar'
    _description = 'Trụ cột DDA'
    _order = 'sequence, id'

    code = fields.Char('Mã', required=True, help='T1 … T10')
    name = fields.Char('Trụ cột', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    pass_score = fields.Float('Ngưỡng đạt (sàn)', default=7.0, help='Thang 10. Dùng để tính khoảng thiếu khi kê đơn.')
    dso_score = fields.Float('Chuẩn DSO', default=8.5)
    is_knockout = fields.Boolean('Điểm liệt', help='Chưa đạt ngưỡng thì gắn cờ đỏ và khoá các gói khác.')
    description = fields.Text('Tiêu chí con / barem')

    _code_uniq = models.Constraint('unique(code)', 'Mã trụ cột phải là duy nhất.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for pillar in self:
            pillar.display_name = f'{pillar.code} · {pillar.name}'
